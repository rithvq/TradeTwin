from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.trades.models import uid
from app.trades.terms import digest

from .access import aligned, consignment, exists, fail, simulated
from .ledger import record, touch, view
from .models import Assignment, Event
from .quantities import items


def event(db, ctx, ident, payload):
    trade, row, _ = consignment(db, ctx, ident, "shipment.event.record", lock=True)
    simulated(trade)
    fingerprint = digest(payload.model_dump(mode="json"))
    previous = db.scalar(
        select(Event).where(
            Event.consignment_id == row.id, Event.client_event_id == str(payload.client_event_id)
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            fail("IDEMPOTENCY_CONFLICT", "Event identity was reused with different content.")
        return view(previous, trade, ctx)
    assignment = exists(db, Assignment, payload.assignment_id)
    if (
        row.active_assignment_id != assignment.id
        or assignment.consignment_id != row.id
        or assignment.status != "ACCEPTED"
        or assignment.driver_user_id != ctx.user.id
    ):
        fail("FORBIDDEN", "Use your current accepted assignment.", status=403)
    state = row.movement_status
    kind = payload.event_type
    transitions = {
        "PICKUP_CONFIRMED": ("NOT_STARTED", "PICKED_UP"),
        "DEPARTED": ("PICKED_UP", "IN_TRANSIT"),
        "ARRIVED": ("IN_TRANSIT", "ARRIVED"),
    }
    if row.planning_status == "CANCELLED" or state == "DELIVERY_CLOSED":
        fail(
            "INVALID_MOVEMENT_TRANSITION", "Movement observations are closed for this consignment."
        )
    if kind in transitions:
        expected, target = transitions[kind]
        if state != expected:
            fail("INVALID_MOVEMENT_TRANSITION", f"{kind} requires {expected}.")
        if kind == "PICKUP_CONFIRMED":
            aligned(row)
            if row.planning_status != "PREPARING":
                fail("INVALID_MOVEMENT_TRANSITION", "Prepare the consignment before pickup.")
            goods = items(db, row.id)
            submitted = {str(i.consignment_item_id): i for i in payload.payload.items}
            if len(submitted) != len(payload.payload.items) or set(submitted) != {
                i.id for i in goods
            }:
                fail(
                    "ALLOCATION_CONFLICT", "Pickup must include every allocated line exactly once."
                )
            if payload.payload.actual_gross_weight_kg > Decimal(
                assignment.vehicle_snapshot["declared_payload_capacity_kg"]
            ):
                fail(
                    "CAPACITY_CONFLICT", "Actual declared weight exceeds accepted vehicle capacity."
                )
            if (
                row.plan_json["package_type"] != "BULK"
                and payload.payload.actual_package_count <= 0
            ):
                fail("VALIDATION_ERROR", "Pickup requires a positive package count.", status=422)
            for item in goods:
                supplied = submitted[item.id]
                if supplied.uqc != item.uqc or supplied.loaded_quantity != item.allocated_quantity:
                    fail(
                        "ALLOCATION_CONFLICT",
                        "Loaded quantity and UQC must match final allocation.",
                    )
                item.loaded_quantity = supplied.loaded_quantity
        row.movement_status = target
    elif kind == "DELIVERY_HANDOVER_REPORTED" and state != "ARRIVED":
        fail(
            "INVALID_MOVEMENT_TRANSITION",
            "Handover requires arrival; it does not accept or close goods.",
        )
    projected = True
    location = (
        {
            "latitude": str(payload.latitude),
            "longitude": str(payload.longitude),
            "occurred_at": payload.occurred_at.isoformat(),
        }
        if payload.latitude is not None and payload.longitude is not None
        else None
    )
    if kind == "LOCATION_REPORTED" and location:
        projected = not row.latest_location_json or payload.occurred_at >= datetime.fromisoformat(
            row.latest_location_json["occurred_at"]
        )
        if projected:
            row.latest_location_json = location
    if kind == "ETA_UPDATED":
        projected = not row.latest_eta_json or payload.occurred_at >= datetime.fromisoformat(
            row.latest_eta_json["occurred_at"]
        )
        if projected:
            row.latest_eta_json = {
                **payload.payload.model_dump(mode="json"),
                "occurred_at": payload.occurred_at.isoformat(),
            }
    from .attachments import link

    ev = Event(
        id=uid(),
        consignment_id=row.id,
        assignment_id=assignment.id,
        client_event_id=str(payload.client_event_id),
        request_hash=fingerprint,
        event_type=kind,
        occurred_at=payload.occurred_at,
        recorded_by_user_id=ctx.user.id,
        recorded_by_organization_id=ctx.org_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        notes=payload.notes,
        payload_json=payload.payload.model_dump(mode="json"),
        projection_applied=projected,
        execution_mode=trade.execution_mode,
    )
    db.add(ev)
    link(db, ctx, trade, row, ev, payload.evidence_attachment_ids)
    touch(row)
    record(
        db,
        ctx,
        "MOVEMENT_EVENT_RECORDED",
        ev,
        trade,
        row,
        {"event_type": kind, "projection_applied": projected},
    )
    from .schedules import refresh_triggers

    refresh_triggers(db, ctx, trade)
    return {
        **view(ev, trade, ctx),
        "recorded_at": view(ev)["created_at"],
        "movement_status": row.movement_status,
    }
