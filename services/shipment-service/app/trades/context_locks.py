"""Shared registry-before-trade locking and factual-context invalidation."""

from sqlalchemy import inspect, text

REGISTRY_LOCK = 884931
FACTUAL_CODES = {
    "RECIPIENT_FACTS_CONFIRMED",
    "AGREEMENT_CONFIRMED",
    "CONSIGNMENT_PLAN_CHANGED",
    "CONSIGNMENT_ALLOCATED",
    "CONSIGNMENT_PLAN_UPDATED",
    "CONSIGNMENT_PREPARED",
    "CONSIGNMENT_CANCELLED",
    "CONSIGNMENT_REVISION_REVIEW",
    "ASSIGNMENT_ACCEPTED",
    "ASSIGNMENT_SUPERSEDED",
    "ASSIGNMENT_CANCELLED",
    "DOCUMENT_REVIEW_SUBMITTED",
    "DOCUMENT_SOURCE_REPLACED",
    "DOCUMENT_ARCHIVED",
    "DOCUMENT_MAPPING_CONFIRMED",
    "DOCUMENT_VERIFICATION_OBSERVED",
    "DOCUMENT_MANUAL_ATTESTATION_RECORDED",
    "DOCUMENT_PORTAL_ATTESTATION_RECORDED",
    "MANUAL_OBSERVATION_REVIEWED",
    "COMPLIANCE_FACTS_APPROVED",
    "COMPLIANCE_FACTS_RETURNED",
    "COMPLIANCE_TURNOVER_APPROVED",
    "LOADING_MANIFEST_PREPARED",
    "TRANSPORT_EVIDENCE_APPROVED",
    "TRANSPORT_EVIDENCE_RETURNED",
    "COMPLIANCE_BINDINGS_PREPARED",
    "COMPLIANCE_HOLD_RAISED",
    "COMPLIANCE_HOLD_CREATED",
    "COMPLIANCE_HOLD_RELEASED",
    "COMPLIANCE_PICKUP_CONSUMED",
    "COMPLIANCE_DEPARTURE_CONSUMED",
}


def registry_lock(db, exclusive=False):
    if db.get_bind().dialect.name == "postgresql":
        name = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        db.execute(text(f"SELECT {name}({REGISTRY_LOCK})"))
    elif db.get_bind().dialect.name == "sqlite":
        raw = db.connection().connection.driver_connection
        if not raw.in_transaction:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def phase4_installed(db):
    if "phase4_installed" not in db.info:
        db.info["phase4_installed"] = inspect(db.get_bind()).has_table("trade_compliance_contexts")
    return db.info["phase4_installed"]


def bump_context(db, trade_id, code):
    if not trade_id or not phase4_installed(db):
        return
    from .models import now

    db.execute(
        text(
            "INSERT INTO trade_compliance_contexts "
            "(trade_id, context_version, last_changed_at, last_change_code) "
            "VALUES (:trade, 1, :at, :code) ON CONFLICT (trade_id) DO UPDATE SET "
            "context_version = trade_compliance_contexts.context_version + 1, "
            "last_changed_at = excluded.last_changed_at, "
            "last_change_code = excluded.last_change_code"
        ),
        {
            "trade": str(trade_id).replace("-", "")
            if db.get_bind().dialect.name == "sqlite"
            else str(trade_id),
            "at": now().isoformat() if db.get_bind().dialect.name == "sqlite" else now(),
            "code": code,
        },
    )


def invalidate(db, trade, action, summary):
    if not trade or db.info.get("defer_compliance_context"):
        return
    accepted = "ACCEPTED" in action and any(
        word in action for word in ("OFFER", "AMENDMENT", "REVISION")
    )
    if action in FACTUAL_CODES or accepted:
        bump_context(db, trade.id, action)
