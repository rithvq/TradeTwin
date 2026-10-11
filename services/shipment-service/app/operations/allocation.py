"""Trade-first locking makes reservations and accepted-amendment validation atomic."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import delete, select

from app.trades.errors import TradeError, pydantic_fields
from app.trades.ledger import revision_facts
from app.trades.models import Item, Participant, Revision, uid

from .access import aligned, before_pickup, consignment, fail, match, party
from .ledger import record, touch
from .models import Assignment, Booking, Consignment, ConsignmentItem
from .quantities import items, reservations
from .schemas import ConsignmentPlan


def validate_plan(db, trade, payload, exclude=None):
    if (
        not trade.accepted_revision_id
        or str(payload.source_accepted_revision_id) != trade.accepted_revision_id
    ):
        fail(
            "REVISION_REVIEW_REQUIRED",
            "Plan against the current accepted agreement.",
            "source_accepted_revision_id",
        )
    facts = db.get(Revision, trade.accepted_revision_id).facts_json
    delivery = facts["delivery_requirements"]
    start, end, arrival = (
        payload.planned_pickup_start,
        payload.planned_pickup_end,
        payload.expected_delivery_at,
    )
    if not (
        datetime.fromisoformat(delivery["pickup_earliest_at"])
        <= start
        <= end
        <= datetime.fromisoformat(delivery["pickup_latest_at"])
        and end <= arrival <= datetime.fromisoformat(delivery["delivery_deadline_at"])
    ):
        fail(
            "VALIDATION_ERROR",
            "Planning windows must fit the accepted pickup and delivery windows.",
            "planned_pickup_start",
            422,
        )
    if (
        payload.declared_net_weight_kg is not None
        and payload.declared_net_weight_kg > payload.declared_gross_weight_kg
    ):
        fail(
            "VALIDATION_ERROR",
            "Net weight cannot exceed gross weight.",
            "declared_net_weight_kg",
            422,
        )
    if payload.package_type != "BULK" and payload.package_count <= 0:
        fail("VALIDATION_ERROR", "Declare a positive package count.", "package_count", 422)
    if str(payload.coordinating_organization_id) not in set(
        db.scalars(select(Participant.organization_id).where(Participant.trade_id == trade.id))
    ):
        fail(
            "VALIDATION_ERROR",
            "Coordinator must be a trade party.",
            "coordinating_organization_id",
            422,
        )
    ordered = {
        r.line_ref: r
        for r in db.scalars(
            select(Item).where(Item.trade_revision_id == trade.accepted_revision_id)
        )
    }
    reserved, seen, result = reservations(db, trade.id, exclude), set(), []
    for index, value in enumerate(payload.items):
        key = str(value.line_ref)
        item = ordered.get(key)
        if key in seen or not item or value.uqc != item.uqc:
            fail(
                "VALIDATION_ERROR",
                "Use each accepted order line once with its exact UQC.",
                f"items.{index}.uqc",
                422,
            )
        seen.add(key)
        if value.allocated_quantity + reserved.get(key, Decimal(0)) > item.quantity:
            fail(
                "ALLOCATION_CONFLICT",
                "Requested quantity exceeds remaining order quantity.",
                f"items.{index}.allocated_quantity",
            )
        result.append((item, value))
    return facts, result


def write_items(db, row, values):
    for item, value in values:
        db.add(
            ConsignmentItem(
                consignment_id=row.id,
                line_ref=item.line_ref,
                source_trade_item_revision_id=item.id,
                allocated_quantity=value.allocated_quantity,
                uqc=item.uqc,
                description_snapshot=item.description,
                specification_snapshot=item.specification,
                cargo_declarations_snapshot=deepcopy(item.cargo_declarations_json),
            )
        )


def create(db, ctx, trade_id, payload):
    trade, _ = party(db, ctx, trade_id, "consignment.plan", "SELLER", True)
    facts, values = validate_plan(db, trade, payload)
    row = Consignment(
        id=uid(),
        trade_id=trade.id,
        reference=f"TT-CN-{uid()[:8].upper()}",
        source_accepted_revision_id=trade.accepted_revision_id,
        coordinating_organization_id=str(payload.coordinating_organization_id),
        execution_mode=trade.execution_mode,
        created_by=ctx.user.id,
        plan_json=payload.model_dump(
            mode="json",
            exclude={"items", "source_accepted_revision_id", "coordinating_organization_id"},
        ),
        pickup_address_snapshot=deepcopy(facts["dispatch_from"]),
        delivery_address_snapshot=deepcopy(facts["ship_to"]),
    )
    db.add(row)
    db.flush()
    write_items(db, row, values)
    touch(trade)
    record(db, ctx, "CONSIGNMENT_ALLOCATED", row, trade, row)
    from .views import consignment_view

    return consignment_view(db, ctx, trade, row)


def release(db, row, status="SUPERSEDED"):
    for assignment in db.scalars(
        select(Assignment).where(
            Assignment.consignment_id == row.id, Assignment.status.in_(["ACCEPTED", "PROPOSED"])
        )
    ):
        assignment.status = status
        touch(assignment)
        for booking in db.scalars(
            select(Booking).where(
                Booking.assignment_id == assignment.id, Booking.released_at.is_(None)
            )
        ):
            from app.trades.models import now

            booking.released_at = now()
    row.active_assignment_id = None


def patch(db, ctx, ident, payload):
    trade, row, _ = consignment(db, ctx, ident, "consignment.plan", "SELLER", True)
    match(ctx, row)
    before_pickup(row)
    aligned(row)
    previous = {
        **row.plan_json,
        "source_accepted_revision_id": row.source_accepted_revision_id,
        "coordinating_organization_id": row.coordinating_organization_id,
        "items": [
            {"line_ref": i.line_ref, "allocated_quantity": str(i.allocated_quantity), "uqc": i.uqc}
            for i in items(db, row.id)
        ],
    }
    try:
        parsed = ConsignmentPlan.model_validate(
            {**previous, **payload.model_dump(mode="json", exclude_unset=True)}
        )
    except ValidationError as exc:
        raise TradeError(
            "VALIDATION_ERROR", "Check the plan.", fields=pydantic_fields(exc.errors())
        ) from exc
    _, values = validate_plan(db, trade, parsed, row.id)
    changes = payload.model_dump(mode="json", exclude_unset=True)
    material = set(changes) - {
        "pickup_contact_name",
        "pickup_contact_phone_e164",
        "delivery_contact_name",
        "delivery_contact_phone_e164",
        "packaging_notes",
        "loading_notes",
        "delivery_notes",
    }
    if material:
        release(db, row)
        row.planning_status = "DRAFT"
    if "items" in changes:
        db.execute(delete(ConsignmentItem).where(ConsignmentItem.consignment_id == row.id))
        write_items(db, row, values)
    row.plan_json = parsed.model_dump(
        mode="json",
        exclude={"items", "source_accepted_revision_id", "coordinating_organization_id"},
    )
    row.coordinating_organization_id = str(parsed.coordinating_organization_id)
    touch(row)
    touch(trade)
    record(
        db,
        ctx,
        "CONSIGNMENT_PLAN_CHANGED",
        row,
        trade,
        row,
        {
            "changed_fields": sorted(changes),
            "before": previous,
            "after": parsed.model_dump(mode="json"),
        },
    )
    from .views import consignment_view

    return consignment_view(db, ctx, trade, row)


def transition(db, ctx, ident, payload, cancel=False):
    trade, row, _ = consignment(
        db, ctx, ident, "consignment.cancel" if cancel else "consignment.plan", "SELLER", True
    )
    match(ctx, row)
    before_pickup(row)
    if cancel:
        row.planning_status = "CANCELLED"
        release(db, row, "CANCELLED")
    else:
        aligned(row)
        facts = db.get(Revision, trade.accepted_revision_id).facts_json
        if not facts["commercial_terms"]["partial_delivery_allowed"]:
            other = reservations(db, trade.id, row.id)
            current = {i.line_ref: i.allocated_quantity for i in items(db, row.id)}
            for i in db.scalars(
                select(Item).where(Item.trade_revision_id == trade.accepted_revision_id)
            ):
                if current.get(i.line_ref, 0) != i.quantity - other.get(i.line_ref, 0):
                    fail(
                        "ALLOCATION_CONFLICT",
                        "Partial delivery is not permitted. "
                        "Prepare all currently unallocated goods together.",
                    )
        row.planning_status = "PREPARING"
    touch(row)
    touch(trade)
    record(
        db,
        ctx,
        "CONSIGNMENT_CANCELLED" if cancel else "CONSIGNMENT_PREPARED",
        row,
        trade,
        row,
        {"reason": getattr(payload, "reason", None)},
    )
    from .views import consignment_view

    return consignment_view(db, ctx, trade, row)


def accept_amendment(db, ctx, trade, revision):
    old = revision_facts(db, db.get(Revision, trade.accepted_revision_id))
    new = revision_facts(db, revision)
    before = {i["line_ref"]: i for i in old["items"]}
    after = {i["line_ref"]: i for i in new["items"]}
    totals = reservations(db, trade.id)
    for key, reserved in totals.items():
        item = after.get(key)
        if not item or item["uqc"] != before[key]["uqc"] or Decimal(item["quantity"]) < reserved:
            fail(
                "ALLOCATION_CONFLICT",
                "Amendment cannot remove allocated lines, change UQC, "
                "or reduce below reservations.",
            )
    material_keys = {
        "description",
        "specification",
        "hsn_code",
        "hazardous_declared",
        "temperature_controlled",
        "temperature_min_c",
        "temperature_max_c",
        "fragile",
        "stackable",
    }
    changed = {
        key for key in totals if any(before[key].get(k) != after[key].get(k) for k in material_keys)
    }
    global_change = any(
        old.get(k) != new.get(k) for k in ("dispatch_from", "ship_to", "delivery_requirements")
    )
    for row in db.scalars(
        select(Consignment).where(
            Consignment.trade_id == trade.id, Consignment.planning_status != "CANCELLED"
        )
    ):
        if global_change or any(i.line_ref in changed for i in items(db, row.id)):
            row.revision_alignment = "REVIEW_REQUIRED"
            touch(row)
            record(db, ctx, "CONSIGNMENT_REVISION_REVIEW", row, trade, row)
    trade.payment_schedule_review_required = True
