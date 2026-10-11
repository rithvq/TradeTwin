from sqlalchemy import select

from app.trades.models import uid

from .access import consignment, exists, fail, has, party
from .ledger import record, touch, view
from .models import Consignment, Dispute, DisputeEvent, Payment, Receipt, ReceiptLine


def dispute_view(db, ctx, trade, row):
    return {
        **view(row, trade, ctx),
        "events": [
            view(e, trade)
            for e in db.scalars(
                select(DisputeEvent)
                .where(DisputeEvent.dispute_id == row.id)
                .order_by(DisputeEvent.created_at, DisputeEvent.id)
            )
        ],
        "allowed_actions": [
            p for p in ("dispute.comment", "dispute.resolve") if has(db, ctx, p, trade.id)
        ],
    }


def create(db, ctx, trade_id, payload):
    trade, _ = party(db, ctx, trade_id, "dispute.open", lock=True)
    cn = None
    if payload.consignment_id:
        _, cn, _ = consignment(db, ctx, payload.consignment_id)
        if cn.trade_id != trade.id:
            fail("VALIDATION_ERROR", "Consignment belongs to another trade.", status=422)
    if payload.receipt_line_id:
        line = exists(db, ReceiptLine, payload.receipt_line_id)
        receipt = exists(db, Receipt, line.receipt_id)
        source = exists(db, Consignment, receipt.consignment_id)
        if (
            source.trade_id != trade.id
            or (cn and cn.id != source.id)
            or (payload.uqc and payload.uqc != line.uqc)
        ):
            fail(
                "VALIDATION_ERROR", "Receipt source or UQC does not match this dispute.", status=422
            )
        cn = source
    if payload.payment_id:
        payment = exists(db, Payment, payload.payment_id)
        if payment.trade_id != trade.id:
            fail("VALIDATION_ERROR", "Payment belongs to another trade.", status=422)
        # Operational roles cannot use disputes as a financial-data lookup.
        from .access import has

        if not (
            has(db, ctx, "payment.report", trade.id, "BUYER")
            or has(db, ctx, "payment.acknowledge", trade.id, "SELLER")
        ):
            fail("FORBIDDEN", "Payment-source disputes require finance authority.", status=403)
    row = Dispute(
        id=uid(),
        trade_id=trade.id,
        consignment_id=cn.id if cn else None,
        receipt_line_id=str(payload.receipt_line_id) if payload.receipt_line_id else None,
        payment_id=str(payload.payment_id) if payload.payment_id else None,
        dispute_json=payload.model_dump(mode="json", exclude={"evidence_attachment_ids"}),
        opened_by_organization_id=ctx.org_id,
        created_by=ctx.user.id,
    )
    db.add(row)
    from .attachments import link

    link(db, ctx, trade, cn, row, payload.evidence_attachment_ids)
    record(db, ctx, "DISPUTE_OPENED", row, trade, cn)
    return dispute_view(db, ctx, trade, row)


def update(db, ctx, ident, payload, action):
    row = exists(db, Dispute, ident)
    trade, _ = party(
        db,
        ctx,
        row.trade_id,
        "dispute.comment" if action == "COMMENT" else "dispute.resolve",
        lock=True,
    )
    db.refresh(row)
    if row.status in {"RESOLVED", "WITHDRAWN"}:
        fail("INVALID_MOVEMENT_TRANSITION", "This dispute is closed.")
    if action == "PROPOSAL" and row.status != "OPEN":
        fail("INVALID_MOVEMENT_TRANSITION", "Decide the active proposal before replacing it.")
    if action == "WITHDRAWAL" and row.opened_by_organization_id != ctx.org_id:
        fail("FORBIDDEN", "Only the opening party can withdraw an unresolved dispute.", status=403)
    event = DisputeEvent(
        id=uid(),
        dispute_id=row.id,
        event_type=action,
        text=getattr(payload, "text", None)
        or getattr(payload, "resolution_text", None)
        or getattr(payload, "reason", None)
        or "Accepted resolution",
        outcome=getattr(payload, "outcome", None),
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    if action == "DECISION":
        if (
            row.status != "RESOLUTION_PROPOSED"
            or str(payload.proposal_id) != row.active_proposal_id
        ):
            fail("STALE_VERSION", "Decide the exact active resolution proposal.", status=412)
        previous = db.scalar(
            select(DisputeEvent).where(
                DisputeEvent.proposal_id == row.active_proposal_id,
                DisputeEvent.actor_organization_id == ctx.org_id,
            )
        )
        if previous:
            fail("IDEMPOTENCY_CONFLICT", "This party already decided this proposal.")
        event.proposal_id, event.outcome = row.active_proposal_id, payload.decision
    db.add(event)
    db.flush()
    if action == "PROPOSAL":
        row.active_proposal_id, row.status = event.id, "RESOLUTION_PROPOSED"
    elif action == "WITHDRAWAL":
        row.status = "WITHDRAWN"
    elif action == "DECISION":
        if payload.decision == "REJECT":
            row.status, row.active_proposal_id = "OPEN", None
        elif (
            len(
                list(
                    db.scalars(
                        select(DisputeEvent).where(
                            DisputeEvent.proposal_id == row.active_proposal_id,
                            DisputeEvent.outcome == "ACCEPT",
                        )
                    )
                )
            )
            == 2
        ):
            row.status = "RESOLVED"
    cn = exists(db, Consignment, row.consignment_id) if row.consignment_id else None
    from .attachments import link

    link(db, ctx, trade, cn, event, getattr(payload, "evidence_attachment_ids", []))
    touch(row)
    record(db, ctx, f"DISPUTE_{action}", event, trade, cn)
    return dispute_view(db, ctx, trade, row)
