"""Operational access is party-scoped or assignment-scoped, never role-selector based."""

from sqlalchemy import select

from app.trades.access import grants, membership, participant_role, require
from app.trades.errors import TradeError, field
from app.trades.models import Trade

from .models import Assignment, Consignment


def fail(code, message, path=None, status=409, details=None):
    raise TradeError(code, message, status, [field(path, message)] if path else [], details)


def exists(db, model, ident):
    row = db.get(model, str(ident))
    if not row:
        fail("NOT_FOUND", "Record not found.", status=404)
    return row


def lock_trade(db, trade_id):
    from app.trades.context_locks import registry_lock

    registry_lock(db)
    row = db.scalar(
        select(Trade)
        .where(Trade.id == str(trade_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row:
        fail("NOT_FOUND", "Trade not found.", status=404)
    return row


def party(db, ctx, trade_id, permission="consignment.read", side=None, lock=False):
    trade = lock_trade(db, trade_id) if lock else exists(db, Trade, trade_id)
    role = participant_role(db, trade.id, ctx.org_id)
    if not role:
        fail("NOT_FOUND", "Trade not found.", status=404)
    if side and role != side:
        fail("FORBIDDEN", "This action belongs to the other trade party.", status=403)
    require(db, ctx.user, ctx.org_id, permission, trade.id, role)
    return trade, role


def consignment(db, ctx, ident, permission="consignment.read", side=None, lock=False):
    row = exists(db, Consignment, ident)
    trade = lock_trade(db, row.trade_id) if lock else exists(db, Trade, row.trade_id)
    if lock:
        db.refresh(row)
    role = participant_role(db, trade.id, ctx.org_id)
    if role:
        party(db, ctx, trade.id, permission, side)
    else:
        if side or permission not in {
            "consignment.read",
            "shipment.event.record",
            "attachment.upload",
            "evidence.read",
            "assignment.respond",
            "compliance.read",
            "transport.evidence.prepare",
            "transport.evidence.review",
            "dispatch.packet.prepare",
            "dispatch.packet.read",
            "dispatch.packet.acknowledge",
            "dispatch.authorisation.request",
        }:
            fail("FORBIDDEN", "Buyer/seller authority is required.", status=403)
        require(db, ctx.user, ctx.org_id, permission, trade.id)
        from sqlalchemy import inspect

        if permission in {
            "consignment.read",
            "attachment.upload",
            "transport.evidence.prepare",
            "transport.evidence.review",
        } and inspect(db.connection()).has_table("freight_rfqs"):
            from app.freight.access import invited_scope

            if invited_scope(db, ctx, row, permission):
                return trade, row, role
        assignments = list(
            db.scalars(
                select(Assignment).where(
                    Assignment.consignment_id == row.id,
                    Assignment.carrier_organization_id == ctx.org_id,
                    Assignment.status.in_(["PROPOSED", "ACCEPTED"]),
                )
            )
        )
        capabilities = {
            g.capability
            for g in grants(db, membership(db, ctx.user, ctx.org_id), trade.id)
            if g.permission_code == permission
        }
        dispatcher = bool({"CARRIER_DISPATCHER", "CARRIER_EVIDENCE_REVIEWER"} & capabilities)
        current_driver = any(
            a.id == row.active_assignment_id
            and a.driver_user_id == ctx.user.id
            and a.status == "ACCEPTED"
            for a in assignments
        )
        if not assignments or not (dispatcher or ("DRIVER" in capabilities and current_driver)):
            fail("NOT_FOUND", "Consignment not found.", status=404)
        if permission == "shipment.event.record" and not current_driver:
            fail("FORBIDDEN", "Only the current assigned driver can record movement.", status=403)
    return trade, row, role


def has(db, ctx, permission, trade_id=None, side=None):
    try:
        require(db, ctx.user, ctx.org_id, permission, trade_id, side)
        return True
    except TradeError:
        return False


def match(ctx, row):
    if ctx.if_match != f'"{row.row_version}"':
        fail("STALE_VERSION", "Record changed. Reload before retrying.", status=412)


def before_pickup(row):
    if row.movement_status != "NOT_STARTED" or row.planning_status == "CANCELLED":
        fail(
            "INVALID_MOVEMENT_TRANSITION", "Only unpicked, uncancelled consignments can be changed."
        )


def aligned(row):
    if row.revision_alignment != "CURRENT":
        fail(
            "REVISION_REVIEW_REQUIRED",
            "Accepted terms changed. Cancel and recreate this consignment after review.",
        )
