"""Manual reports, counterparty decisions and paise allocation ledger. No money movement."""

from sqlalchemy import select

from app.trades.access import participant_role
from app.trades.models import Participant, Revision, uid

from .access import exists, fail, has, party
from .ledger import record, view
from .models import (
    Obligation,
    Payment,
    PaymentAllocation,
    PaymentDecision,
    Schedule,
    ScheduleLine,
    TriggerEvent,
)
from .schedules import net_allocated, obligation_view, schedule_view


def decisions(db, row):
    return list(
        db.scalars(
            select(PaymentDecision)
            .where(PaymentDecision.payment_id == row.id)
            .order_by(PaymentDecision.created_at, PaymentDecision.id)
        )
    )


def status(db, row):
    result = "MANUAL_REPORTED"
    mapping = {
        "ACKNOWLEDGE": "COUNTERPARTY_ACKNOWLEDGED",
        "DISPUTE": "DISPUTED",
        "WITHDRAW": "WITHDRAWN",
        "VOID": "VOID",
    }
    for decision in decisions(db, row):
        result = mapping.get(decision.decision, result)
    return result


def payment_view(db, ctx, trade, row):
    entries = list(
        db.scalars(
            select(PaymentAllocation)
            .where(PaymentAllocation.payment_id == row.id)
            .order_by(PaymentAllocation.created_at, PaymentAllocation.id)
        )
    )
    history = decisions(db, row)
    pending = [
        d
        for d in history
        if d.decision == "VOID_REQUEST" and not any(a.void_request_id == d.id for a in history)
    ]
    return {
        **view(row, trade, ctx),
        "status": status(db, row),
        "net_allocated_minor": str(net_allocated(db, payment_id=row.id)),
        "decisions": [view(d, trade) for d in history],
        "allocations": [view(e, trade) for e in entries],
        "pending_void_request": view(pending[-1], trade) if pending else None,
        "provider_verification": "NOT_ASSESSED",
    }


def report(db, ctx, trade_id, payload):
    trade, _ = party(db, ctx, trade_id, "payment.report", "BUYER", True)
    if not trade.accepted_revision_id:
        fail("PAYMENT_PLAN_REVIEW_REQUIRED", "Payment reports require an accepted agreement.")
    sides = {
        p.participant_role: p.organization_id
        for p in db.scalars(select(Participant).where(Participant.trade_id == trade.id))
    }
    row = Payment(
        id=uid(),
        trade_id=trade.id,
        payer_organization_id=sides["BUYER"],
        payee_organization_id=sides["SELLER"],
        currency="INR",
        amount_minor=int(payload.amount_minor),
        paid_on=payload.paid_on,
        method=payload.method,
        declared_reference=payload.declared_reference,
        notes=payload.notes,
        reported_by_user_id=ctx.user.id,
        reported_by_organization_id=ctx.org_id,
    )
    duplicate = bool(
        payload.declared_reference
        and db.scalar(
            select(Payment.id).where(
                Payment.trade_id == trade.id,
                Payment.declared_reference == payload.declared_reference,
            )
        )
    )
    db.add(row)
    from .attachments import link

    link(db, ctx, trade, None, row, payload.evidence_attachment_ids)
    record(db, ctx, "PAYMENT_MANUALLY_REPORTED", row, trade)
    return {**payment_view(db, ctx, trade, row), "duplicate_reference_warning": duplicate}


def decide(db, ctx, ident, payload, action):
    row = exists(db, Payment, ident)
    trade, _ = party(
        db,
        ctx,
        row.trade_id,
        "payment.report" if action == "WITHDRAW" else "payment.acknowledge",
        "BUYER" if action == "WITHDRAW" else "SELLER",
        True,
    )
    current = status(db, row)
    if current in {"VOID", "WITHDRAWN"}:
        fail("PAYMENT_NOT_ACKNOWLEDGED", "This payment record is inactive.")
    if action == "WITHDRAW" and any(d.decision == "ACKNOWLEDGE" for d in decisions(db, row)):
        fail(
            "PAYMENT_NOT_ACKNOWLEDGED",
            "Acknowledged reports require bilateral record void, not withdrawal.",
        )
    reason = getattr(payload, "reason", None) or getattr(payload, "notes", None)
    decision = PaymentDecision(
        id=uid(),
        payment_id=row.id,
        decision=action,
        reason=reason,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(decision)
    record(
        db,
        ctx,
        f"PAYMENT_{action}",
        decision,
        trade,
        detail={"payment_id": row.id, "reason": reason},
    )
    return payment_view(db, ctx, trade, row)


def allocate(db, ctx, ident, payload):
    row = exists(db, Payment, ident)
    trade, _ = party(db, ctx, row.trade_id, "payment.allocate", "SELLER", True)
    db.scalar(select(Payment).where(Payment.id == row.id).with_for_update())
    if status(db, row) != "COUNTERPARTY_ACKNOWLEDGED":
        fail(
            "PAYMENT_NOT_ACKNOWLEDGED",
            "Only counterparty-acknowledged active payments can be allocated.",
        )
    if trade.payment_schedule_review_required or not trade.active_payment_schedule_id:
        fail(
            "PAYMENT_PLAN_REVIEW_REQUIRED", "Approve the current goods schedule before allocating."
        )
    if (
        sum(int(a.amount_minor) for a in payload.allocations) + net_allocated(db, payment_id=row.id)
        > row.amount_minor
    ):
        fail(
            "PAYMENT_ALLOCATION_EXCEEDED",
            "Batch exceeds this payment's unallocated acknowledged funds.",
        )
    pending = {}
    entries = []
    # The trade lock serializes payments targeting the same obligations.
    for value in sorted(payload.allocations, key=lambda a: str(a.obligation_ref)):
        obligation = db.scalar(
            select(Obligation).where(Obligation.id == str(value.obligation_ref)).with_for_update()
        )
        if (
            not obligation
            or obligation.trade_id != trade.id
            or obligation.currency != row.currency
            or obligation.payer_organization_id != row.payer_organization_id
            or obligation.payee_organization_id != row.payee_organization_id
        ):
            fail(
                "VALIDATION_ERROR",
                "Payment and obligation must match trade, currency, payer and payee.",
                "allocations",
                422,
            )
        line = db.scalar(
            select(ScheduleLine).where(
                ScheduleLine.schedule_id == trade.active_payment_schedule_id,
                ScheduleLine.obligation_ref == obligation.id,
            )
        )
        if not line:
            fail(
                "PAYMENT_PLAN_REVIEW_REQUIRED", "Obligation is not in the active approved schedule."
            )
        pending[obligation.id] = pending.get(obligation.id, 0) + int(value.amount_minor)
        if net_allocated(db, obligation.id) + pending[obligation.id] > line.face_amount_minor:
            fail(
                "OBLIGATION_ALLOCATION_EXCEEDED",
                "Batch exceeds the obligation's remaining face amount.",
            )
        entry = PaymentAllocation(
            id=uid(),
            payment_id=row.id,
            obligation_ref=obligation.id,
            basis_schedule_line_id=line.id,
            entry_type="ALLOCATION",
            amount_minor=int(value.amount_minor),
            actor_user_id=ctx.user.id,
            actor_organization_id=ctx.org_id,
        )
        entries.append(entry)
    db.add_all(entries)
    for entry in entries:
        record(db, ctx, "PAYMENT_ALLOCATED", entry, trade)
    return payment_view(db, ctx, trade, row)


def reverse_entry(db, ctx, trade, original, amount, reason):
    if original.entry_type != "ALLOCATION" or amount > net_allocated(db, original_id=original.id):
        fail("PAYMENT_ALLOCATION_EXCEEDED", "Reversal exceeds the unreversed original allocation.")
    entry = PaymentAllocation(
        id=uid(),
        payment_id=original.payment_id,
        obligation_ref=original.obligation_ref,
        basis_schedule_line_id=original.basis_schedule_line_id,
        entry_type="REVERSAL",
        amount_minor=amount,
        reverses_allocation_id=original.id,
        reason=reason,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(entry)
    record(
        db,
        ctx,
        "PAYMENT_ALLOCATION_REVERSED",
        entry,
        trade,
        detail={"reason": reason, "actual_refund": "NOT_PERFORMED"},
    )
    return entry


def reverse(db, ctx, ident, payload):
    original = exists(db, PaymentAllocation, ident)
    payment = exists(db, Payment, original.payment_id)
    trade, _ = party(db, ctx, payment.trade_id, "payment.allocation.reverse", "SELLER", True)
    entry = reverse_entry(db, ctx, trade, original, int(payload.amount_minor), payload.reason)
    return view(entry, trade, ctx)


def void_request(db, ctx, ident, payload):
    payment = exists(db, Payment, ident)
    trade, _ = party(db, ctx, payment.trade_id, "payment.void.propose", lock=True)
    if status(db, payment) in {"VOID", "WITHDRAWN"}:
        fail("PAYMENT_NOT_ACKNOWLEDGED", "Inactive records cannot be voided again.")
    if payment_view(db, ctx, trade, payment)["pending_void_request"]:
        fail("IDEMPOTENCY_CONFLICT", "An unresolved void request already exists.")
    request = PaymentDecision(
        id=uid(),
        payment_id=payment.id,
        decision="VOID_REQUEST",
        reason=payload.reason,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(request)
    record(
        db,
        ctx,
        "PAYMENT_VOID_REQUESTED",
        request,
        trade,
        detail={"payment_id": payment.id, "reason": payload.reason},
    )
    return payment_view(db, ctx, trade, payment)


def void_decision(db, ctx, ident, payload):
    payment = exists(db, Payment, ident)
    trade, _ = party(db, ctx, payment.trade_id, "payment.void.approve", lock=True)
    request = exists(db, PaymentDecision, payload.void_request_id)
    if (
        request.payment_id != payment.id
        or request.decision != "VOID_REQUEST"
        or request.actor_organization_id == ctx.org_id
    ):
        fail(
            "FORBIDDEN",
            "The other finance organisation must decide this exact void request.",
            status=403,
        )
    if any(d.void_request_id == request.id for d in decisions(db, payment)) or status(
        db, payment
    ) in {"VOID", "WITHDRAWN"}:
        fail("IDEMPOTENCY_CONFLICT", "This void request is no longer active.")
    if payload.decision == "REJECT" and not payload.reason:
        fail("VALIDATION_ERROR", "Rejecting a void request requires a reason.", "reason", 422)
    decision = PaymentDecision(
        id=uid(),
        payment_id=payment.id,
        decision=f"VOID_{payload.decision}",
        void_request_id=request.id,
        reason=payload.reason,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(decision)
    if payload.decision == "APPROVE":
        for original in db.scalars(
            select(PaymentAllocation).where(
                PaymentAllocation.payment_id == payment.id,
                PaymentAllocation.entry_type == "ALLOCATION",
            )
        ):
            remaining = net_allocated(db, original_id=original.id)
            if remaining:
                reverse_entry(db, ctx, trade, original, remaining, request.reason)
        db.add(
            PaymentDecision(
                payment_id=payment.id,
                decision="VOID",
                reason=request.reason,
                actor_user_id=ctx.user.id,
                actor_organization_id=ctx.org_id,
            )
        )
    record(
        db,
        ctx,
        "PAYMENT_VOID_DECIDED",
        decision,
        trade,
        detail={"decision": payload.decision, "actual_refund": "NOT_PERFORMED"},
    )
    return payment_view(db, ctx, trade, payment)


def settlement(db, ctx, trade):
    side = participant_role(db, trade.id, ctx.org_id)
    if not side or not any(
        has(db, ctx, p, trade.id, side)
        for p in (
            "payment.settlement.read",
            "payment.report",
            "payment.acknowledge",
            "payment_schedule.propose",
            "payment_schedule.approve",
        )
    ):
        fail("FORBIDDEN", "Finance authority is required to view settlement.", status=403)
    payments = list(
        db.scalars(
            select(Payment)
            .where(Payment.trade_id == trade.id)
            .order_by(Payment.created_at, Payment.id)
        )
    )
    obligations = (
        [
            obligation_view(db, trade, line)
            for line in db.scalars(
                select(ScheduleLine)
                .where(ScheduleLine.schedule_id == trade.active_payment_schedule_id)
                .order_by(ScheduleLine.line_order)
            )
        ]
        if trade.active_payment_schedule_id
        else []
    )
    current = {p.id: status(db, p) for p in payments}
    acknowledged = [p for p in payments if current[p.id] == "COUNTERPARTY_ACKNOWLEDGED"]
    net = sum(net_allocated(db, payment_id=p.id) for p in payments)
    ack_minor = sum(p.amount_minor for p in acknowledged)
    return {
        "trade_id": trade.id,
        "execution_mode": trade.execution_mode,
        "request_id": ctx.request_id,
        "pricing_basis": db.get(Revision, trade.accepted_revision_id).facts_json["pricing_basis"],
        "accepted_quoted_goods_total_minor": db.get(
            Revision, trade.accepted_revision_id
        ).pricing_summary_json["quoted_goods_total_minor"],
        "active_schedule_id": trade.active_payment_schedule_id,
        "schedule_status": "REVIEW_REQUIRED"
        if trade.payment_schedule_review_required
        else "ACTIVE"
        if trade.active_payment_schedule_id
        else "NOT_PROPOSED",
        "schedule_review_required": trade.payment_schedule_review_required,
        "scheduled_goods_minor": str(sum(int(o["face_amount_minor"]) for o in obligations)),
        "reported_payment_minor": str(
            sum(p.amount_minor for p in payments if current[p.id] not in {"VOID", "WITHDRAWN"})
        ),
        "acknowledged_payment_minor": str(ack_minor),
        "net_allocated_minor": str(net),
        "unallocated_acknowledged_minor": str(
            sum(p.amount_minor - net_allocated(db, payment_id=p.id) for p in acknowledged)
        ),
        "outstanding_scheduled_minor": str(sum(int(o["remaining_minor"]) for o in obligations)),
        "overapplied_minor": str(sum(int(o["overapplied_minor"]) for o in obligations)),
        "disputed_payment_minor": str(
            sum(p.amount_minor for p in payments if current[p.id] == "DISPUTED")
        ),
        "obligations": obligations,
        "trigger_history": [
            view(event, trade)
            for event in db.scalars(
                select(TriggerEvent)
                .where(TriggerEvent.trade_id == trade.id)
                .order_by(TriggerEvent.created_at, TriggerEvent.id)
            )
        ],
        "payments": [payment_view(db, ctx, trade, p) for p in payments],
        "schedules": [
            schedule_view(db, ctx, trade, s)
            for s in db.scalars(
                select(Schedule)
                .where(Schedule.trade_id == trade.id)
                .order_by(Schedule.schedule_number)
            )
        ],
        "provider_verification": "NOT_ASSESSED",
        "final_invoice_reconciliation": "NOT_ASSESSED",
        "allowed_actions": [
            p
            for p in (
                "payment_schedule.propose",
                "payment_schedule.approve",
                "payment.report",
                "payment.acknowledge",
                "payment.allocate",
                "payment.allocation.reverse",
                "payment.void.propose",
                "payment.void.approve",
            )
            if has(db, ctx, p, trade.id, side)
        ],
    }
