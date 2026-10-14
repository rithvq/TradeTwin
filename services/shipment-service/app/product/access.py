"""Workspace selection never expands resource or field-level access."""

from sqlalchemy import select

from app.operations.access import consignment, exists, fail, has, lock_trade
from app.operations.models import Assignment, Consignment
from app.trades.access import grants, membership, participant_role, require, trade_access
from app.trades.errors import TradeError
from app.trades.models import Trade


def workspace(db, ctx, ident, lock=False):
    trade = lock_trade(db, ident) if lock else exists(db, Trade, ident)
    side = participant_role(db, trade.id, ctx.org_id)
    if side:
        trade_access(db, ctx.user, ctx.org_id, trade.id)
        return (
            trade,
            side,
            list(
                db.scalars(
                    select(Consignment)
                    .where(Consignment.trade_id == trade.id)
                    .order_by(Consignment.id)
                )
            ),
        )
    require(db, ctx.user, ctx.org_id, "consignment.read", trade.id)
    query = (
        select(Consignment)
        .join(Assignment, Assignment.consignment_id == Consignment.id)
        .where(
            Consignment.trade_id == trade.id,
            Assignment.carrier_organization_id == ctx.org_id,
            Assignment.status.in_(["PROPOSED", "ACCEPTED"]),
        )
        .distinct()
    )
    visible = []
    for cn in db.scalars(query):
        try:
            consignment(db, ctx, cn.id)
            visible.append(cn)
        except TradeError:
            continue
    if not visible:
        fail("WORKSPACE_ACCESS_DENIED", "Trade workspace not found.", status=404)
    return trade, None, visible


def capabilities(db, ctx, trade_id=None):
    return sorted(
        {g.permission_code for g in grants(db, membership(db, ctx.user, ctx.org_id), trade_id)}
    )


def privileged(db, ctx, permission):
    return require(db, ctx.user, ctx.org_id, permission)


def affordable_view(db, ctx, trade):
    return any(
        has(db, ctx, p, trade.id)
        for p in [
            "payment.report",
            "payment.acknowledge",
            "payment_schedule.approve",
            "payment_schedule.propose",
        ]
    )
