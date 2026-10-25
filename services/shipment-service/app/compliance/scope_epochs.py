"""Database scope revisions are authoritative; messages are never freshness evidence."""

from sqlalchemy import inspect, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.trades.models import now, uid

from .models_computation import DependencyScopeEpoch as Epoch

GROUPS = (
    "FACTS",
    "ASSIGNMENT",
    "TERMS",
    "LOADING",
    "BINDING",
    "TRANSPORT",
    "TURNOVER",
    "VERIFICATION",
    "RESERVATION",
)


def installed(db):
    if "computation_tables" not in db.info:
        db.info["computation_tables"] = inspect(db.connection()).has_table(Epoch.__tablename__)
    return db.info["computation_tables"]


def key(trade_id, group):
    return f"trade:{trade_id}:{group}"


def advance(db, keys, code):
    if not installed(db):
        return
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    for scope in sorted(set(keys)):
        statement = insert(Epoch).values(
            scope_key=scope, generation_id=uid(), epoch=1, last_change_code=code, changed_at=now()
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[Epoch.scope_key],
                set_={"epoch": Epoch.epoch + 1, "last_change_code": code, "changed_at": now()},
            )
        )
    # Core upserts may have changed a row already loaded for a prior witness.
    for row in list(db.identity_map.values()):
        if isinstance(row, Epoch):
            db.expire(row)


def capture(db, trade_id, document_types):
    keys = (
        ["global:VEHICLES", "global:VERIFICATION"]
        + [key(trade_id, group) for group in GROUPS]
        + [key(trade_id, "DOC:" + kind) for kind in document_types]
    )
    query = select(Epoch).where(Epoch.scope_key.in_(keys)).execution_options(populate_existing=True)
    rows = {r.scope_key: r for r in db.scalars(query)}
    missing = set(keys) - rows.keys()
    advance(db, missing, "INITIALISE_SCOPE")
    rows = {r.scope_key: r for r in db.scalars(query)}
    return {
        scope: {
            "generation_id": r.generation_id,
            "epoch": r.epoch,
            "last_change_code": r.last_change_code,
            "initialised_now": scope in missing,
        }
        for scope, r in rows.items()
    }


def on_change(db, trade, action, subject=None, document=None):
    if not installed(db):
        return
    scopes = []
    if trade:
        groups = set()
        if (
            action.startswith("DOCUMENT_")
            or action.startswith("EVIDENCE_")
            or action.startswith("MANUAL_")
        ):
            if document:
                groups.add("DOC:" + document.document_type)
            if "VERIFICATION" in action or "ATTESTATION" in action or "OBSERVATION" in action:
                groups.add("VERIFICATION")
        if action.startswith("ASSIGNMENT_"):
            groups.add("ASSIGNMENT")
        if action in {"AGREEMENT_CONFIRMED", "AMENDMENT_ACCEPTED"} or (
            "ACCEPTED" in action and "REVISION" in action
        ):
            groups.add("TERMS")
        if action.startswith(
            ("CONSIGNMENT_", "LOADING_MANIFEST_", "COMPLIANCE_PICKUP_", "COMPLIANCE_DEPARTURE_")
        ):
            groups.add("LOADING")
        if action.startswith("COMPLIANCE_FACTS_"):
            groups.add("FACTS")
        if action.startswith("TRANSPORT_EVIDENCE_"):
            groups.add("TRANSPORT")
        if action.startswith("COMPLIANCE_TURNOVER_"):
            groups.add("TURNOVER")
        if action == "COMPLIANCE_BINDINGS_PREPARED":
            groups.update({"BINDING", "RESERVATION"})
        scopes += [key(trade.id, group) for group in groups]
    # Global vehicle/provider/key changes have existing registry-before-resource locks.
    if action.startswith("VEHICLE_"):
        scopes.append("global:VEHICLES")
    if action.startswith(("VERIFICATION_", "TRUSTED_KEY_")):
        scopes.append("global:VERIFICATION")
    advance(db, scopes, action)
