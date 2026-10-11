"""Physical receipt, inspection, closure, and their reversals are independent facts."""

from decimal import Decimal

from sqlalchemy import select

from app.trades.models import now, uid
from app.trades.terms import digest

from .access import consignment, exists, fail, match, simulated
from .ledger import record, touch, view
from .models import Booking, Closure, Inspection, Receipt, ReceiptHead, ReceiptLine, Reopening
from .quantities import effective_lines, inspection_totals, items, summary


def receipt_view(db, ctx, trade, row):
    head = db.scalar(
        select(ReceiptHead).where(ReceiptHead.receipt_chain_id == row.receipt_chain_id)
    )
    result = view(row, trade, ctx)
    result["effective"] = head.effective_receipt_id == row.id
    result["head_etag"] = f'"{head.row_version}"'
    result["etag"] = result["head_etag"]
    result["lines"] = []
    for line in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == row.id)):
        a, r = inspection_totals(db, line.id)
        result["lines"].append(
            {
                **view(line),
                "accepted_quantity": str(a),
                "rejected_quantity": str(r),
                "pending_inspection_quantity": str(line.delivered_quantity - a - r),
                "decisions": [
                    view(d, trade)
                    for d in db.scalars(
                        select(Inspection)
                        .where(Inspection.receipt_line_id == line.id)
                        .order_by(Inspection.created_at, Inspection.id)
                    )
                ],
            }
        )
    return result


def receive(db, ctx, ident, payload, correcting=None):
    trade, row, _ = consignment(
        db, ctx, ident, "receipt.correct" if correcting else "receipt.record", "BUYER", True
    )
    simulated(trade)
    fingerprint = digest(payload.model_dump(mode="json"))
    duplicate = db.scalar(
        select(Receipt).where(
            Receipt.consignment_id == row.id,
            Receipt.client_receipt_id == str(payload.client_receipt_id),
        )
    )
    if duplicate:
        if duplicate.request_hash != fingerprint or duplicate.supersedes_receipt_id != correcting:
            fail("IDEMPOTENCY_CONFLICT", "Receipt identity was reused with different content.")
        return receipt_view(db, ctx, trade, duplicate)
    if row.movement_status != "ARRIVED" or row.current_delivery_closure_id:
        fail(
            "INVALID_MOVEMENT_TRANSITION",
            "Receive/correct goods only after arrival and before delivery closure.",
        )
    head = None
    if correcting:
        original = exists(db, Receipt, correcting)
        head = db.scalar(
            select(ReceiptHead)
            .where(ReceiptHead.receipt_chain_id == original.receipt_chain_id)
            .with_for_update()
        )
        if (
            original.consignment_id != row.id
            or not head
            or head.effective_receipt_id != original.id
        ):
            fail("STALE_VERSION", "Correct only the effective receipt head.", status=412)
        match(ctx, head)
        for line in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == original.id)):
            if sum(inspection_totals(db, line.id)) > 0:
                fail(
                    "INSPECTION_QUANTITY_EXCEEDED",
                    "Reverse effective inspections before correcting receipt.",
                )
    goods = {i.id: i for i in items(db, row.id)}
    totals = {}
    for line in effective_lines(db, row.id):
        if line.receipt_id != correcting:
            totals[line.consignment_item_id] = (
                totals.get(line.consignment_item_id, Decimal(0)) + line.delivered_quantity
            )
    seen = set()
    for index, value in enumerate(payload.lines):
        key = str(value.consignment_item_id)
        item = goods.get(key)
        if key in seen or not item or value.uqc != item.uqc:
            fail(
                "VALIDATION_ERROR",
                "Use each consignment line once with its original UQC.",
                f"lines.{index}.uqc",
                422,
            )
        seen.add(key)
        if (
            item.loaded_quantity is None
            or totals.get(key, Decimal(0)) + value.delivered_quantity > item.loaded_quantity
        ):
            fail(
                "RECEIPT_QUANTITY_EXCEEDED",
                "Cumulative receipt exceeds loaded quantity.",
                f"lines.{index}.delivered_quantity",
            )
    receipt = Receipt(
        id=uid(),
        consignment_id=row.id,
        client_receipt_id=str(payload.client_receipt_id),
        request_hash=fingerprint,
        receipt_chain_id=head.receipt_chain_id if head else uid(),
        supersedes_receipt_id=correcting,
        received_at=payload.received_at,
        received_by_user_id=ctx.user.id,
        receiving_organization_id=ctx.org_id,
        receipt_json=payload.model_dump(mode="json", exclude={"lines", "evidence_attachment_ids"}),
    )
    db.add(receipt)
    db.flush()
    for value in payload.lines:
        db.add(
            ReceiptLine(
                receipt_id=receipt.id,
                **value.model_dump(exclude={"consignment_item_id"}),
                consignment_item_id=str(value.consignment_item_id),
            )
        )
    if head:
        head.effective_receipt_id = receipt.id
        touch(head)
    else:
        db.add(
            ReceiptHead(
                receipt_chain_id=receipt.receipt_chain_id,
                consignment_id=row.id,
                effective_receipt_id=receipt.id,
                created_by=ctx.user.id,
            )
        )
    from .attachments import link

    link(db, ctx, trade, row, receipt, payload.evidence_attachment_ids)
    touch(row)
    record(
        db,
        ctx,
        "RECEIPT_CORRECTED" if correcting else "RECEIPT_RECORDED",
        receipt,
        trade,
        row,
        {"supersedes_receipt_id": correcting, "reason": getattr(payload, "reason", None)},
    )
    from .schedules import refresh_triggers

    refresh_triggers(db, ctx, trade)
    return receipt_view(db, ctx, trade, receipt)


def inspect_goods(db, ctx, ident, payload):
    receipt = exists(db, Receipt, ident)
    trade, row, _ = consignment(db, ctx, receipt.consignment_id, "goods.accept", "BUYER", True)
    simulated(trade)
    head = db.scalar(
        select(ReceiptHead).where(ReceiptHead.effective_receipt_id == receipt.id).with_for_update()
    )
    if not head:
        fail("STALE_VERSION", "Inspect only the effective receipt.", status=412)
    lines = {
        line.id: line
        for line in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == receipt.id))
    }
    seen, decisions = set(), []
    for value in payload.decisions:
        key = str(value.receipt_line_id)
        line = lines.get(key)
        if not line or key in seen:
            fail("VALIDATION_ERROR", "Select a receipt line once.", "decisions", 422)
        seen.add(key)
        accepted, rejected = inspection_totals(db, key)
        if (
            accepted + rejected + value.accepted_quantity + value.rejected_quantity
            > line.delivered_quantity
        ):
            fail("INSPECTION_QUANTITY_EXCEEDED", "Decision exceeds pending inspection quantity.")
        decision = Inspection(
            id=uid(),
            receipt_line_id=key,
            entry_type="DECISION",
            accepted_quantity=value.accepted_quantity,
            rejected_quantity=value.rejected_quantity,
            rejection_reason=value.rejection_reason,
            notes=value.notes,
            actor_user_id=ctx.user.id,
            actor_organization_id=ctx.org_id,
        )
        db.add(decision)
        from .attachments import link

        link(db, ctx, trade, row, decision, value.evidence_attachment_ids)
        record(db, ctx, "INSPECTION_RECORDED", decision, trade, row)
        decisions.append(view(decision, trade, ctx))
    touch(row)
    from .schedules import refresh_triggers

    refresh_triggers(db, ctx, trade)
    return {
        "execution_mode": trade.execution_mode,
        "request_id": ctx.request_id,
        "decisions": decisions,
        "receipt_summary": summary(db, row),
    }


def reverse(db, ctx, ident, payload):
    original = exists(db, Inspection, ident)
    line = exists(db, ReceiptLine, original.receipt_line_id)
    receipt = exists(db, Receipt, line.receipt_id)
    trade, row, _ = consignment(
        db, ctx, receipt.consignment_id, "goods.acceptance.reverse", "BUYER", True
    )
    simulated(trade)
    if original.entry_type != "DECISION" or db.scalar(
        select(Inspection.id).where(Inspection.reverses_decision_id == original.id)
    ):
        fail(
            "INSPECTION_QUANTITY_EXCEEDED",
            "Only an unreversed original decision can be fully reversed.",
        )
    reversal = Inspection(
        id=uid(),
        receipt_line_id=line.id,
        entry_type="REVERSAL",
        accepted_quantity=original.accepted_quantity,
        rejected_quantity=original.rejected_quantity,
        notes=payload.reason,
        reverses_decision_id=original.id,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(reversal)
    touch(row)
    record(
        db,
        ctx,
        "INSPECTION_REVERSED",
        reversal,
        trade,
        row,
        {"reason": payload.reason, "reverses_decision_id": original.id},
    )
    from .schedules import refresh_triggers

    refresh_triggers(db, ctx, trade)
    return view(reversal, trade, ctx)


def close(db, ctx, ident, payload):
    trade, row, _ = consignment(db, ctx, ident, "receipt.close", "BUYER", True)
    simulated(trade)
    match(ctx, row)
    if row.movement_status != "ARRIVED" or row.current_delivery_closure_id:
        fail("INVALID_MOVEMENT_TRANSITION", "Close only an arrived, open delivery recording.")
    closure = Closure(
        id=uid(),
        consignment_id=row.id,
        closed_by_user_id=ctx.user.id,
        notes=payload.notes,
        quantity_summary_json={},
    )
    row.current_delivery_closure_id, row.movement_status = closure.id, "DELIVERY_CLOSED"
    closure.quantity_summary_json = {
        "lines": summary(db, row),
        "execution_mode": trade.execution_mode,
    }
    db.add(closure)
    for booking in db.scalars(
        select(Booking).where(
            Booking.assignment_id == row.active_assignment_id, Booking.released_at.is_(None)
        )
    ):
        booking.released_at = now()
    touch(row)
    record(db, ctx, "DELIVERY_CLOSED", closure, trade, row)
    from .schedules import refresh_triggers

    refresh_triggers(db, ctx, trade)
    return view(closure, trade, ctx)


def reopen(db, ctx, ident, payload):
    closure = exists(db, Closure, ident)
    trade, row, _ = consignment(db, ctx, closure.consignment_id, "receipt.reopen", "BUYER", True)
    simulated(trade)
    match(ctx, row)
    if row.current_delivery_closure_id != closure.id or db.scalar(
        select(Reopening.id).where(Reopening.closure_id == closure.id)
    ):
        fail(
            "INVALID_MOVEMENT_TRANSITION", "Only the current delivery closure can be reopened once."
        )
    reopening = Reopening(
        id=uid(),
        closure_id=closure.id,
        reason=payload.reason,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(reopening)
    row.current_delivery_closure_id, row.movement_status = None, "ARRIVED"
    touch(row)
    record(db, ctx, "DELIVERY_REOPENED", reopening, trade, row, {"reason": payload.reason})
    from .schedules import refresh_triggers

    refresh_triggers(db, ctx, trade)
    return view(reopening, trade, ctx)
