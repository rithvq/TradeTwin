"""Bilateral goods schedules and retractable factual triggers; no tax/bank inference."""

from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.trades.access import aware
from app.trades.models import Approval, Item, Participant, Revision, now, uid
from app.trades.terms import digest

from .access import exists, fail, match, party
from .ledger import record, touch, view
from .models import (
    Consignment,
    Event,
    Inspection,
    Obligation,
    PaymentAllocation,
    Receipt,
    Schedule,
    ScheduleApproval,
    ScheduleLine,
    TriggerEvent,
)
from .quantities import effective_lines, inspection_totals, items


def amounts(total, percentages):
    with localcontext() as ctx:
        ctx.prec = 50
        exact = [Decimal(total) * Decimal(p) / 100 for p in percentages]
        floors = [int(v.to_integral_value(rounding=ROUND_FLOOR)) for v in exact]
        remainder = total - sum(floors)
        for index in sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))[
            :remainder
        ]:
            floors[index] += 1
        return floors


def net_allocated(db, obligation_ref=None, payment_id=None, original_id=None):
    query = select(PaymentAllocation)
    if obligation_ref:
        query = query.where(PaymentAllocation.obligation_ref == obligation_ref)
    if payment_id:
        query = query.where(PaymentAllocation.payment_id == payment_id)
    if original_id:
        from sqlalchemy import or_

        query = query.where(
            or_(
                PaymentAllocation.id == original_id,
                PaymentAllocation.reverses_allocation_id == original_id,
            )
        )
    return sum(
        (r.amount_minor if r.entry_type == "ALLOCATION" else -r.amount_minor)
        for r in db.scalars(query)
    )


def candidate(db, trade):
    if not trade.accepted_revision_id:
        fail("REVISION_REVIEW_REQUIRED", "An accepted agreement is required.")
    revision = db.get(Revision, trade.accepted_revision_id)
    total = int(revision.pricing_summary_json["quoted_goods_total_minor"])
    terms = revision.facts_json["commercial_terms"]
    mode = terms["payment_mode"]
    lines, questions = [], []

    def line(label, amount, trigger, offset=0, date=None):
        return {
            "label": label,
            "face_amount_minor": str(amount),
            "trigger": trigger,
            "offset_days": offset,
            "fixed_due_on": date,
        }

    if mode == "ON_DELIVERY":
        lines = [line("Goods on full delivery", total, "FULL_DELIVERY")]
    elif mode == "ADVANCE":
        advance = terms.get("advance_minor")
        if advance is None:
            questions.append(
                "Specify the agreed advance amount through commercial amendment or clarification."
            )
        else:
            lines = [line("Agreed advance", int(advance), "ORDER_CONFIRMATION")]
            if int(advance) < total:
                questions.append(
                    "Agree an explicit trigger and date for the remaining goods balance."
                )
    elif mode == "CREDIT":
        questions.append("Agree the credit-period anchor and scope.")
        if terms.get("credit_days") is None:
            questions.append("Agree the credit period.")
    else:
        milestones = terms["milestone_schedule"]
        shares = amounts(total, [m["percent_of_quoted_goods"] for m in milestones])
        mapping = {
            "DISPATCH": "FULL_DISPATCH",
            "DELIVERY": "FULL_DELIVERY",
            "ACCEPTANCE": "FULL_ACCEPTANCE",
        }
        lines = [
            line(m["label"], a, mapping.get(m["trigger"], m["trigger"]), date=m.get("due_on"))
            for m, a in zip(milestones, shares, strict=True)
        ]
        if terms["partial_delivery_allowed"]:
            questions.append("Confirm full-trade milestone scope despite partial deliveries.")
    return {
        "accepted_revision_id": revision.id,
        "execution_mode": trade.execution_mode,
        "quoted_goods_total_minor": str(total),
        "pricing_basis": revision.facts_json["pricing_basis"],
        "status": "NEEDS_CLARIFICATION" if questions else "READY",
        "questions": questions,
        "lines": lines,
        "additional_tax_freight": "NOT_ASSESSED",
        "final_invoice_reconciliation": "NOT_ASSESSED",
    }


def trigger_facts(db, trade):
    ordered = {
        i.line_ref: i.quantity
        for i in db.scalars(
            select(Item).where(Item.trade_revision_id == trade.accepted_revision_id)
        )
    }
    totals = {key: {} for key in ("FULL_DISPATCH", "FULL_DELIVERY", "FULL_ACCEPTANCE")}
    sources = {key: [] for key in totals}
    for cn in db.scalars(
        select(Consignment).where(
            Consignment.trade_id == trade.id, Consignment.planning_status != "CANCELLED"
        )
    ):
        goods = {i.id: i for i in items(db, cn.id)}
        departure = db.scalar(
            select(Event)
            .where(Event.consignment_id == cn.id, Event.event_type == "DEPARTED")
            .order_by(Event.created_at)
            .limit(1)
        )
        if departure:
            sources["FULL_DISPATCH"].append(
                {"id": departure.id, "occurred_at": aware(departure.occurred_at).isoformat()}
            )
            for i in goods.values():
                totals["FULL_DISPATCH"][i.line_ref] = totals["FULL_DISPATCH"].get(
                    i.line_ref, Decimal(0)
                ) + (i.loaded_quantity or Decimal(0))
        for line in effective_lines(db, cn.id):
            item = goods[line.consignment_item_id]
            receipt = db.get(Receipt, line.receipt_id)
            accepted, _ = inspection_totals(db, line.id)
            for trigger, quantity in (
                ("FULL_DELIVERY", line.delivered_quantity),
                ("FULL_ACCEPTANCE", accepted),
            ):
                totals[trigger][item.line_ref] = (
                    totals[trigger].get(item.line_ref, Decimal(0)) + quantity
                )
                if trigger == "FULL_DELIVERY":
                    sources[trigger].append(
                        {"id": line.id, "occurred_at": aware(receipt.received_at).isoformat()}
                    )
                else:
                    decisions = list(
                        db.scalars(select(Inspection).where(Inspection.receipt_line_id == line.id))
                    )
                    reversed_ids = {
                        d.reverses_decision_id for d in decisions if d.entry_type == "REVERSAL"
                    }
                    sources[trigger].extend(
                        {"id": d.id, "occurred_at": aware(d.created_at).isoformat()}
                        for d in decisions
                        if d.entry_type == "DECISION"
                        and d.id not in reversed_ids
                        and d.accepted_quantity > 0
                    )
    result = {
        "ORDER_CONFIRMATION": (
            bool(trade.accepted_revision_id),
            [
                {
                    "id": a.id,
                    "occurred_at": aware(a.decided_at).isoformat(),
                }
                for a in db.scalars(
                    select(Approval).where(
                        Approval.revision_id == trade.accepted_revision_id,
                        Approval.decision == "ACCEPT",
                    )
                )
            ],
        )
    }
    for trigger in totals:
        result[trigger] = (
            bool(ordered)
            and all(totals[trigger].get(k, Decimal(0)) >= v for k, v in ordered.items()),
            sources[trigger],
        )
    return result


def refresh_triggers(db, ctx, trade):
    db.flush()
    if not trade.accepted_revision_id:
        return
    for trigger, (met, sources) in trigger_facts(db, trade).items():
        previous = db.scalar(
            select(TriggerEvent)
            .where(TriggerEvent.trade_id == trade.id, TriggerEvent.trigger == trigger)
            .order_by(TriggerEvent.created_at.desc(), TriggerEvent.id.desc())
            .limit(1)
        )
        was_met = bool(previous and previous.event_kind == "ACTIVATED")
        if was_met == met:
            continue
        event = TriggerEvent(
            id=uid(),
            trade_id=trade.id,
            accepted_revision_id=trade.accepted_revision_id,
            trigger=trigger,
            event_kind="ACTIVATED" if met else "RETRACTED",
            occurred_at=max(
                (datetime.fromisoformat(s["occurred_at"]) for s in sources), default=now()
            )
            if met
            else now(),
            source_references_json={"sources": sources},
            retracts_event_id=previous.id if not met else None,
        )
        db.add(event)
        if not met:
            trade.payment_schedule_review_required = True
            touch(trade)
        record(
            db,
            ctx,
            "PAYMENT_TRIGGER_CHANGED",
            event,
            trade,
            detail={"trigger": trigger, "event_kind": event.event_kind},
        )


def schedule_view(db, ctx, trade, row):
    return {
        **view(row, trade, ctx),
        "lines": [
            view(line, trade)
            for line in db.scalars(
                select(ScheduleLine)
                .where(ScheduleLine.schedule_id == row.id)
                .order_by(ScheduleLine.line_order)
            )
        ],
        "approvals": [
            view(a, trade)
            for a in db.scalars(
                select(ScheduleApproval).where(ScheduleApproval.schedule_id == row.id)
            )
        ],
    }


def validate_terms(db, trade, payload, generated):
    revision = db.get(Revision, trade.accepted_revision_id)
    terms = revision.facts_json["commercial_terms"]
    positive = [line for line in payload.lines if int(line.face_amount_minor)]

    def shape(line):
        return (
            int(line.face_amount_minor),
            line.trigger,
            line.offset_days,
            line.fixed_due_on.isoformat() if line.fixed_due_on else None,
        )

    expected = [
        (int(line["face_amount_minor"]), line["trigger"], line["offset_days"], line["fixed_due_on"])
        for line in generated["lines"]
        if int(line["face_amount_minor"])
    ]
    actual = [shape(line) for line in positive]
    if terms["payment_mode"] in {"ON_DELIVERY", "MILESTONE"} and actual != expected:
        fail(
            "VALIDATION_ERROR",
            "This schedule contradicts accepted payment terms; use a commercial amendment.",
            "lines",
            422,
        )
    if terms["payment_mode"] == "ADVANCE" and terms.get("advance_minor") is not None:
        advance = int(terms["advance_minor"])
        if (
            sum(
                int(line.face_amount_minor)
                for line in positive
                if line.trigger == "ORDER_CONFIRMATION" and line.offset_days == 0
            )
            != advance
        ):
            fail("VALIDATION_ERROR", "Preserve the explicitly agreed advance amount.", "lines", 422)
    if terms["payment_mode"] == "CREDIT" and terms.get("credit_days") is not None:
        if any(line.offset_days != terms["credit_days"] for line in positive):
            fail("VALIDATION_ERROR", "Preserve the agreed credit period.", "lines", 422)


def propose(db, ctx, trade_id, payload):
    trade, _ = party(db, ctx, trade_id, "payment_schedule.propose", lock=True)
    match(ctx, trade)
    if str(payload.accepted_revision_id) != trade.accepted_revision_id:
        fail("PAYMENT_PLAN_REVIEW_REQUIRED", "Propose against the current accepted revision.")
    generated = candidate(db, trade)
    total = int(generated["quoted_goods_total_minor"])
    if sum(int(line.face_amount_minor) for line in payload.lines) != total:
        fail(
            "VALIDATION_ERROR",
            "Schedule must sum exactly to the accepted quoted goods amount.",
            "lines",
            422,
        )
    clarification = (
        generated["status"] == "NEEDS_CLARIFICATION" or trade.active_payment_schedule_id is not None
    )
    if clarification and not payload.reason:
        fail("VALIDATION_ERROR", "Clarification or replacement requires a reason.", "reason", 422)
    validate_terms(db, trade, payload, generated)
    parties = {
        p.participant_role: p.organization_id
        for p in db.scalars(select(Participant).where(Participant.trade_id == trade.id))
    }
    retained, parsed = set(), []
    for order, line in enumerate(payload.lines, 1):
        if line.obligation_ref:
            obligation = exists(db, Obligation, line.obligation_ref)
            if obligation.trade_id != trade.id or obligation.id in retained:
                fail(
                    "VALIDATION_ERROR",
                    "Retain unique obligations from this trade only.",
                    "lines",
                    422,
                )
        else:
            obligation = Obligation(
                id=uid(),
                trade_id=trade.id,
                payer_organization_id=parties["BUYER"],
                payee_organization_id=parties["SELLER"],
                currency="INR",
            )
            db.add(obligation)
        retained.add(obligation.id)
        parsed.append(
            {**line.model_dump(mode="json"), "obligation_ref": obligation.id, "line_order": order}
        )
    funded = {
        o.id
        for o in db.scalars(select(Obligation).where(Obligation.trade_id == trade.id))
        if net_allocated(db, o.id) > 0
    }
    if not funded <= retained:
        fail(
            "OBLIGATION_ALLOCATION_EXCEEDED",
            "Replacement must retain every funded obligation, even with zero face amount.",
        )
    number = (
        db.scalar(select(func.max(Schedule.schedule_number)).where(Schedule.trade_id == trade.id))
        or 0
    ) + 1
    row = Schedule(
        id=uid(),
        trade_id=trade.id,
        accepted_revision_id=trade.accepted_revision_id,
        schedule_number=number,
        source="BILATERAL_CLARIFICATION" if clarification else "AGREEMENT_DERIVED",
        quoted_goods_total_minor=total,
        due_timezone=payload.due_timezone,
        reason=payload.reason,
        content_hash=digest(
            {
                "accepted_revision_id": trade.accepted_revision_id,
                "due_timezone": payload.due_timezone,
                "lines": parsed,
            }
        ),
        created_by_user_id=ctx.user.id,
        created_by_organization_id=ctx.org_id,
    )
    db.add(row)
    db.flush()
    from datetime import date

    for values in parsed:
        values["face_amount_minor"] = int(values["face_amount_minor"])
        values["fixed_due_on"] = (
            date.fromisoformat(values["fixed_due_on"]) if values["fixed_due_on"] else None
        )
        db.add(ScheduleLine(schedule_id=row.id, **values))
    touch(trade)
    record(db, ctx, "PAYMENT_SCHEDULE_PROPOSED", row, trade)
    return schedule_view(db, ctx, trade, row)


def approve(db, ctx, ident, payload):
    row = exists(db, Schedule, ident)
    trade, _ = party(db, ctx, row.trade_id, "payment_schedule.approve", lock=True)
    db.refresh(row)
    if row.status != "PROPOSED" or row.accepted_revision_id != trade.accepted_revision_id:
        fail(
            "PAYMENT_PLAN_REVIEW_REQUIRED",
            "Schedule is inactive or its accepted agreement changed.",
        )
    if payload.content_hash != row.content_hash:
        fail("IDEMPOTENCY_CONFLICT", "Approve only the exact proposed schedule hash.")
    if db.scalar(
        select(ScheduleApproval.id).where(
            ScheduleApproval.schedule_id == row.id, ScheduleApproval.organization_id == ctx.org_id
        )
    ):
        fail("IDEMPOTENCY_CONFLICT", "This organisation already decided this schedule.")
    if payload.decision == "REJECT" and not payload.reason:
        fail("VALIDATION_ERROR", "Rejection requires a reason.", "reason", 422)
    approval = ScheduleApproval(
        id=uid(),
        schedule_id=row.id,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        decision=payload.decision,
        content_hash=payload.content_hash,
        reason=payload.reason,
    )
    db.add(approval)
    db.flush()
    if payload.decision == "REJECT":
        row.status = "REJECTED"
    elif (
        len(
            list(
                db.scalars(
                    select(ScheduleApproval).where(
                        ScheduleApproval.schedule_id == row.id,
                        ScheduleApproval.decision == "ACCEPT",
                    )
                )
            )
        )
        == 2
    ):
        scheduled_refs = set(
            db.scalars(
                select(ScheduleLine.obligation_ref).where(ScheduleLine.schedule_id == row.id)
            )
        )
        funded = {
            o.id
            for o in db.scalars(select(Obligation).where(Obligation.trade_id == trade.id))
            if net_allocated(db, o.id) > 0
        }
        if not funded <= scheduled_refs:
            fail(
                "OBLIGATION_ALLOCATION_EXCEEDED",
                "Funded obligations changed after proposal. Retain them in a replacement schedule.",
            )
        if trade.active_payment_schedule_id:
            db.get(Schedule, trade.active_payment_schedule_id).status = "SUPERSEDED"
            db.flush()
        row.status = "ACTIVE"
        trade.active_payment_schedule_id, trade.payment_schedule_review_required = row.id, False
    touch(trade)
    record(
        db,
        ctx,
        "PAYMENT_SCHEDULE_DECIDED",
        approval,
        trade,
        detail={"decision": payload.decision, "schedule_hash": row.content_hash},
    )
    refresh_triggers(db, ctx, trade)
    return schedule_view(db, ctx, trade, row)


def obligation_view(db, trade, line):
    net = net_allocated(db, line.obligation_ref)
    trigger = db.scalar(
        select(TriggerEvent)
        .where(TriggerEvent.trade_id == trade.id, TriggerEvent.trigger == line.trigger)
        .order_by(TriggerEvent.created_at.desc(), TriggerEvent.id.desc())
        .limit(1)
    )
    met = line.trigger == "FIXED_DATE" or bool(trigger and trigger.event_kind == "ACTIVATED")
    due = line.fixed_due_on
    activated = trigger
    if trigger and trigger.event_kind == "RETRACTED":
        activated = db.get(TriggerEvent, trigger.retracts_event_id)
    if activated and not due:
        due = aware(activated.occurred_at).astimezone(
            ZoneInfo(db.get(Schedule, line.schedule_id).due_timezone)
        ).date() + timedelta(days=line.offset_days)
    remaining, over = max(line.face_amount_minor - net, 0), max(net - line.face_amount_minor, 0)
    return {
        **view(line, trade),
        "active_schedule_line_id": line.id,
        "trigger_met": met,
        "due_on": due.isoformat() if due else None,
        "net_allocated_minor": str(net),
        "remaining_minor": str(remaining),
        "overapplied_minor": str(over),
        "status": "OVERAPPLIED"
        if over
        else "FUNDED"
        if not remaining
        else "DUE"
        if met
        else "AWAITING_TRIGGER",
    }
