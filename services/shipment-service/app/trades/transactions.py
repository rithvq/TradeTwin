from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .access import actor, membership, require, trade_access
from .context_locks import registry_lock
from .errors import TradeError
from .models import Amendment, Idempotency, Offer, Organization, User, now
from .terms import digest


@dataclass
class Context:
    user: User
    org_id: str | None
    request_id: str
    if_match: str | None = None


def context(request, db, organization_required=True):
    user = actor(db)
    org_id = request.headers.get("X-Organization-Id") if organization_required else None
    if organization_required:
        if not org_id:
            raise TradeError("ORGANIZATION_REQUIRED", "Select your organisation.", 403)
        try:
            org_id = str(UUID(org_id))
        except ValueError as exc:
            raise TradeError("FORBIDDEN", "Invalid organisation context.", 403) from exc
        membership(db, user, org_id)
    request_id = str(uuid4())
    request.state.request_id = request_id
    return Context(user, org_id, request_id, request.headers.get("If-Match"))


def preflight(db, ctx, request, payload):
    """Replay never bypasses membership, role or capability revocation."""
    parts = request.url.path.removeprefix("/api/v1/").split("/")
    resource, action = parts[0], parts[-1]
    if resource == "organizations":
        if len(parts) > 1:
            permission = {"members": "members.manage", "locations": "locations.manage"}.get(
                action, "organization.edit"
            )
            require(db, ctx.user, ctx.org_id, permission)
        return
    if resource == "trades" and len(parts) == 1:
        require(db, ctx.user, ctx.org_id, "trade.create", side=payload.initiated_by_role)
        return
    if resource == "trades":
        trade_id = parts[1]
    else:
        row = db.get(Offer if resource == "offers" else Amendment, parts[1])
        if not row:
            raise TradeError("NOT_FOUND", "Commercial record not found.", 404)
        trade_id = row.trade_id
    _, side = trade_access(db, ctx.user, ctx.org_id, trade_id, lock=True)
    permission = (
        f"order.confirm.{side.lower()}"
        if action in {"confirmations", "rejections"}
        else "trade.propose_amendment"
        if resource == "amendments" or action == "amendments"
        else "trade.offer"
        if action == "offers"
        else "trade.withdraw_offer"
        if action == "withdrawals"
        else "trade.edit_draft"
    )
    require(db, ctx.user, ctx.org_id, permission, trade_id, side)


def mutate(
    request: Request,
    db,
    operation,
    payload,
    organization_required=True,
    status=200,
    authorize=None,
    conflict_code="IDEMPOTENCY_KEY_REUSED",
):
    try:
        registry_command = request.url.path.startswith(
            "/api/v1/regulations/"
        ) and request.url.path.endswith(
            ("/publications", "/suspensions", "/resolutions", "/source-conflicts")
        )
        registry_command = registry_command or any(
            segment in request.url.path
            for segment in (
                "/memberships",
                "/members",
                "/trusted-keys",
                "/verification-connections",
                "/pan-turnover-declarations/",
                "/vehicles",
            )
        )
        registry_command = registry_command or request.url.path.startswith("/api/v1/routing/")
        registry_command = registry_command or request.url.path.startswith("/api/v1/corridor/")
        registry_command = registry_command or request.url.path.startswith(
            ("/api/v1/readiness/", "/api/v1/deployments/", "/api/v1/pilot-scope-revisions")
        )
        registry_lock(db, exclusive=registry_command)
        ctx = context(request, db, organization_required)
        key = request.headers.get("Idempotency-Key", "")
        if not 1 <= len(key) <= 128:
            raise TradeError(
                "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key of 1 to 128 characters.", 400
            )
        # Always acquire the shared trade before organization/resource locks.
        check = authorize or (lambda session, actor: preflight(session, actor, request, payload))
        check(db, ctx)
        if organization_required:
            db.scalar(select(Organization).where(Organization.id == ctx.org_id).with_for_update())
        else:
            db.scalar(select(User).where(User.id == ctx.user.id).with_for_update())
        check(db, ctx)
        scope = f"org:{ctx.org_id}" if organization_required else f"user:{ctx.user.id}"
        operation_name = f"{request.method}:{request.url.path}"
        fingerprint = digest({"actor": ctx.user.id, "payload": payload.model_dump(mode="json")})
        saved = db.scalar(
            select(Idempotency).where(
                Idempotency.scope_key == scope,
                Idempotency.operation == operation_name,
                Idempotency.idempotency_key == key,
            )
        )
        if saved:
            if saved.request_hash != fingerprint:
                raise TradeError(
                    conflict_code,
                    "This key was used with a different payload or actor.",
                    409,
                )
            body, status_code, etag = (
                saved.response_body_json,
                saved.response_status,
                saved.response_etag,
            )
        else:
            body = operation(db, ctx, payload)
            status_code, etag = status, body.get("etag")
            db.add(
                Idempotency(
                    scope_key=scope,
                    organization_id=ctx.org_id,
                    operation=operation_name,
                    idempotency_key=key,
                    request_hash=fingerprint,
                    response_status=status_code,
                    response_body_json=body,
                    response_etag=etag,
                    expires_at=now() + timedelta(days=7),
                )
            )
        db.commit()
        return JSONResponse(body, status_code=status_code, headers={"ETag": etag} if etag else {})
    except IntegrityError as exc:
        db.rollback()
        raise TradeError(
            "CONCURRENT_CHANGE",
            "A concurrent operation changed this record. Reload and retry.",
            409,
        ) from exc
    except Exception:
        db.rollback()
        raise
