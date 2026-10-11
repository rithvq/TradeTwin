"""Exact quantity projections from effective receipt heads and append-only inspection entries."""

from decimal import Decimal

from sqlalchemy import select

from app.trades.models import Item

from .models import Consignment, ConsignmentItem, Inspection, ReceiptHead, ReceiptLine


def q(value):
    return format(Decimal(value), ".6f") if value is not None else None


def items(db, consignment_id):
    return list(
        db.scalars(
            select(ConsignmentItem)
            .where(ConsignmentItem.consignment_id == consignment_id)
            .order_by(ConsignmentItem.created_at, ConsignmentItem.id)
        )
    )


def reservations(db, trade_id, exclude=None):
    query = (
        select(ConsignmentItem)
        .join(Consignment, Consignment.id == ConsignmentItem.consignment_id)
        .where(Consignment.trade_id == trade_id, Consignment.planning_status != "CANCELLED")
    )
    if exclude:
        query = query.where(Consignment.id != exclude)
    totals = {}
    for row in db.scalars(query):
        totals[row.line_ref] = totals.get(row.line_ref, Decimal(0)) + row.allocated_quantity
    return totals


def availability(db, trade):
    totals = reservations(db, trade.id)
    return [
        {
            "line_ref": r.line_ref,
            "description": r.description,
            "uqc": r.uqc,
            "ordered_quantity": q(r.quantity),
            "reserved_quantity": q(totals.get(r.line_ref, 0)),
            "available_quantity": q(r.quantity - totals.get(r.line_ref, 0)),
        }
        for r in db.scalars(
            select(Item)
            .where(Item.trade_revision_id == trade.accepted_revision_id)
            .order_by(Item.line_no)
        )
    ]


def effective_lines(db, consignment_id):
    return list(
        db.scalars(
            select(ReceiptLine)
            .join(ReceiptHead, ReceiptHead.effective_receipt_id == ReceiptLine.receipt_id)
            .where(ReceiptHead.consignment_id == consignment_id)
            .order_by(ReceiptLine.created_at, ReceiptLine.id)
        )
    )


def inspection_totals(db, line_id):
    accepted, rejected = Decimal(0), Decimal(0)
    for decision in db.scalars(select(Inspection).where(Inspection.receipt_line_id == line_id)):
        sign = 1 if decision.entry_type == "DECISION" else -1
        accepted += sign * decision.accepted_quantity
        rejected += sign * decision.rejected_quantity
    return accepted, rejected


def summary(db, row):
    totals = {}
    for line in effective_lines(db, row.id):
        received, accepted, rejected = totals.get(
            line.consignment_item_id, (Decimal(0), Decimal(0), Decimal(0))
        )
        a, r = inspection_totals(db, line.id)
        totals[line.consignment_item_id] = (
            received + line.delivered_quantity,
            accepted + a,
            rejected + r,
        )
    result = []
    for item in items(db, row.id):
        received, accepted, rejected = totals.get(item.id, (Decimal(0), Decimal(0), Decimal(0)))
        remainder = max((item.loaded_quantity or Decimal(0)) - received, Decimal(0))
        result.append(
            {
                "consignment_item_id": item.id,
                "line_ref": item.line_ref,
                "description": item.description_snapshot,
                "uqc": item.uqc,
                "allocated_quantity": q(item.allocated_quantity),
                "loaded_quantity": q(item.loaded_quantity),
                "received_quantity": q(received),
                "accepted_quantity": q(accepted),
                "rejected_quantity": q(rejected),
                "pending_inspection_quantity": q(received - accepted - rejected),
                "awaiting_receipt_quantity": q(
                    remainder if not row.current_delivery_closure_id else 0
                ),
                "short_quantity": q(remainder if row.current_delivery_closure_id else 0),
                "inspection_status": "NOT_RECEIVED"
                if received == 0
                else "PENDING_INSPECTION"
                if accepted + rejected == 0
                else "PARTIALLY_DECIDED"
                if accepted + rejected < received
                else "DECIDED_WITH_EXCEPTIONS"
                if rejected > 0
                else "ACCEPTED",
            }
        )
    return result
