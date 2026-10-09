"""Request identity and SQL ownership enforcement shared by domain services."""

import os
from contextvars import ContextVar

import httpx
from sqlalchemy import String, event, inspect, text
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LEGACY_OWNER = "legacy-unassigned"
identity: ContextVar[dict | None] = ContextVar("tradetwin_identity", default=None)
credential: ContextVar[str] = ContextVar("tradetwin_credential", default="")


def enabled():
    return os.getenv("PROFILE_AUTH_ENABLED", "true").lower() == "true"


def owner_id():
    return (identity.get() or {}).get("id", LEGACY_OWNER)


def service_headers():
    token = credential.get()
    return {"Authorization": f"Bearer {token}"} if token else {}


class TenantOwned:
    owner_id: Mapped[str] = mapped_column(String(80), default=owner_id, index=True)


@event.listens_for(Session, "do_orm_execute")
def restrict_rows(state):
    if state.is_select or state.is_update or state.is_delete:
        current_owner = owner_id()
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantOwned,
                lambda model: model.owner_id == current_owner,
                include_aliases=True,
            )
        )


@event.listens_for(Session, "before_flush")
def assign_owner(session, _context, _instances):
    for row in session.new:
        if isinstance(row, TenantOwned):
            row.owner_id = owner_id()
    for row in session.dirty | session.deleted:
        if isinstance(row, TenantOwned) and row.owner_id != owner_id():
            raise ValueError("Record belongs to a different profile")


def migrate_ownership(engine, metadata):
    """Add ownership to existing tables without claiming historical data for a new user."""
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(884921)"))
        inspector = inspect(connection)
        existing = set(inspector.get_table_names())
        for table in metadata.sorted_tables:
            if "owner_id" not in table.c or table.name not in existing:
                continue
            name = connection.dialect.identifier_preparer.quote(table.name)
            if "owner_id" not in {col["name"] for col in inspector.get_columns(table.name)}:
                connection.execute(
                    text(
                        f"ALTER TABLE {name} ADD COLUMN owner_id VARCHAR(80) "
                        "NOT NULL DEFAULT 'legacy-unassigned'"
                    )
                )
                connection.execute(
                    text(f"CREATE INDEX ix_{table.name}_owner_id ON {name}(owner_id)")
                )
        if "shipments" in existing and engine.dialect.name == "postgresql":
            for constraint in inspector.get_unique_constraints("shipments"):
                if constraint["column_names"] == ["shipment_reference"]:
                    name = connection.dialect.identifier_preparer.quote(constraint["name"])
                    connection.execute(text(f"ALTER TABLE shipments DROP CONSTRAINT {name}"))
            for index in inspector.get_indexes("shipments"):
                if index["unique"] and index["column_names"] == ["shipment_reference"]:
                    if not index.get("duplicates_constraint"):
                        name = connection.dialect.identifier_preparer.quote(index["name"])
                        connection.execute(text(f"DROP INDEX {name}"))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_shipments_owner_reference "
                    "ON shipments(owner_id, shipment_reference)"
                )
            )


async def resolve_identity(token):
    url = os.getenv("API_SERVICE_URL", "http://127.0.0.1:8000").rstrip("/")
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            f"{url}/auth/session", headers={"Authorization": f"Bearer {token}"}
        )
    if response.status_code == 401:
        return None
    response.raise_for_status()
    user = response.json()
    if not user.get("id") or user["id"] == LEGACY_OWNER:
        return None
    return user


class ProfileMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not enabled() or request.url.path in {"/health", "/ready"}:
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not token:
            return JSONResponse({"detail": "Sign in required"}, status_code=401)
        try:
            user = await resolve_identity(token)
        except httpx.HTTPError:
            return JSONResponse({"detail": "Authentication service unavailable"}, status_code=503)
        if user is None:
            return JSONResponse({"detail": "Session expired"}, status_code=401)
        identity_token = identity.set(user)
        credential_token = credential.set(token)
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            identity.reset(identity_token)
            credential.reset(credential_token)
