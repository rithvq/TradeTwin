"""Carrier consent and declared suitability are not dispatch or freight-price approvals."""

from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import or_, select

from app.trades.access import require
from app.trades.errors import TradeError, pydantic_fields
from app.trades.ledger import registration
from app.trades.models import Organization, User, now, uid

from .access import aligned, before_pickup, consignment, exists, fail, has, match
from .ledger import record, touch, view
from .models import Assignment, Booking, Carrier, Vehicle
from .quantities import items
from .schemas import VehicleInput


def profile(db, ctx, payload):
    require(db, ctx.user, ctx.org_id, "carrier_profile.manage")
    registration(db, payload.gst_registration_id, ctx.org_id)
    row = db.scalar(select(Carrier).where(Carrier.organization_id == ctx.org_id))
    if not row:
        row = Carrier(id=uid(), organization_id=ctx.org_id, created_by=ctx.user.id, row_version=1)
        db.add(row)
    else:
        match(ctx, row)
        touch(row)
    row.profile_json = payload.model_dump(mode="json")
    row.active = payload.active
    record(db, ctx, "CARRIER_PROFILE_DECLARED", row)
    return {**view(row, ctx=ctx), "declaration_status": "SELF_DECLARED"}


def directory(db, ctx, q="", cursor=None):
    query = (
        select(Carrier, Organization)
        .join(Organization, Organization.id == Carrier.organization_id)
        .where(Carrier.active.is_(True))
    )
    if cursor:
        query = query.where(Carrier.id > str(cursor))
    if q:
        query = query.where(
            or_(Organization.legal_name.ilike(f"%{q}%"), Organization.trade_name.ilike(f"%{q}%"))
        )
    rows = [
        (c, o)
        for c, o in db.execute(query.order_by(Carrier.id))
        if c.profile_json["directory_visibility"] == "TRADING_PROFILE"
        or c.organization_id == ctx.org_id
    ][:51]
    return {
        "items": [
            {**view(c), "organization_name": o.legal_name, "declaration_status": "SELF_DECLARED"}
            for c, o in rows[:50]
        ],
        "next_cursor": rows[49][0].id if len(rows) > 50 else None,
    }


def vehicle(db, ctx, payload, ident=None):
    require(db, ctx.user, ctx.org_id, "vehicle.manage")
    if ident:
        row = exists(db, Vehicle, ident)
        if row.carrier_organization_id != ctx.org_id:
            fail("NOT_FOUND", "Vehicle not found.", status=404)
        match(ctx, row)
        try:
            parsed = VehicleInput.model_validate(
                {**row.vehicle_json, **payload.model_dump(mode="json", exclude_unset=True)}
            )
        except ValidationError as exc:
            raise TradeError(
                "VALIDATION_ERROR",
                "Check vehicle declarations.",
                fields=pydantic_fields(exc.errors()),
            ) from exc
        touch(row)
    else:
        parsed = payload
        carrier = db.scalar(
            select(Carrier).where(Carrier.organization_id == ctx.org_id, Carrier.active.is_(True))
        )
        if not carrier:
            fail("VALIDATION_ERROR", "Create an active carrier profile first.", status=422)
        row = Vehicle(id=uid(), carrier_organization_id=ctx.org_id, created_by=ctx.user.id)
        db.add(row)
    row.registration_number = parsed.registration_number
    row.vehicle_json = parsed.model_dump(mode="json")
    row.active = parsed.active
    record(db, ctx, "VEHICLE_DECLARED", row)
    return {**view(row, ctx=ctx), "declaration_status": "SELF_DECLARED"}


def propose(db, ctx, ident, payload):
    trade, row, _ = consignment(db, ctx, ident, "transport.assign", lock=True)
    match(ctx, row)
    before_pickup(row)
    aligned(row)
    if ctx.org_id != row.coordinating_organization_id:
        fail("FORBIDDEN", "Only the coordinating trade party can propose transport.", status=403)
    carrier = db.scalar(
        select(Carrier).where(
            Carrier.organization_id == str(payload.carrier_organization_id),
            Carrier.active.is_(True),
        )
    )
    if not carrier or (
        carrier.profile_json["directory_visibility"] != "TRADING_PROFILE"
        and carrier.organization_id != ctx.org_id
    ):
        fail("VALIDATION_ERROR", "Select an available carrier.", "carrier_organization_id", 422)
    plan = row.plan_json
    from datetime import datetime

    if not (
        payload.booking_start_at <= datetime.fromisoformat(plan["planned_pickup_start"])
        and payload.booking_end_at >= datetime.fromisoformat(plan["expected_delivery_at"])
    ):
        fail(
            "VALIDATION_ERROR",
            "Booking must cover pickup through expected delivery.",
            "booking_end_at",
            422,
        )
    if payload.vehicle_id:
        v = exists(db, Vehicle, payload.vehicle_id)
        if v.carrier_organization_id != carrier.organization_id:
            fail(
                "VALIDATION_ERROR",
                "Suggested vehicle must belong to selected carrier.",
                "vehicle_id",
                422,
            )
    if payload.driver_user_id:
        driver = exists(db, User, payload.driver_user_id)
        require(db, driver, carrier.organization_id, "shipment.event.record", trade.id)
    assignment = Assignment(
        id=uid(),
        consignment_id=row.id,
        carrier_organization_id=carrier.organization_id,
        vehicle_id=str(payload.vehicle_id) if payload.vehicle_id else None,
        driver_user_id=str(payload.driver_user_id) if payload.driver_user_id else None,
        booking_start_at=payload.booking_start_at,
        booking_end_at=payload.booking_end_at,
        notes=payload.notes,
        proposed_by_organization_id=ctx.org_id,
        created_by=ctx.user.id,
    )
    db.add(assignment)
    touch(row)
    record(db, ctx, "ASSIGNMENT_PROPOSED", assignment, trade, row)
    return view(assignment, trade, ctx)


def decide(db, ctx, ident, payload):
    assignment = exists(db, Assignment, ident)
    trade, row, _ = consignment(db, ctx, assignment.consignment_id, "assignment.respond", lock=True)
    if ctx.org_id != assignment.carrier_organization_id or not has(
        db, ctx, "assignment.respond", trade.id
    ):
        fail("FORBIDDEN", "Only the proposed carrier can decide this assignment.", status=403)
    require(db, ctx.user, ctx.org_id, "assignment.respond", trade.id)
    before_pickup(row)
    aligned(row)
    db.refresh(assignment)
    if assignment.status != "PROPOSED":
        fail("INVALID_MOVEMENT_TRANSITION", "This proposal already has a decision.")
    if payload.decision == "DECLINE":
        assignment.status = "DECLINED"
    else:
        carrier = db.scalar(
            select(Carrier).where(Carrier.organization_id == ctx.org_id, Carrier.active.is_(True))
        )
        if not carrier:
            fail("FORBIDDEN", "Carrier profile is inactive.", status=403)
        # Consistent resource ordering serializes bookings across different trades.
        vehicle_row = db.scalar(
            select(Vehicle)
            .where(Vehicle.id == str(payload.vehicle_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        driver = db.scalar(
            select(User)
            .where(User.id == str(payload.driver_user_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not vehicle_row
            or vehicle_row.carrier_organization_id != ctx.org_id
            or not vehicle_row.active
            or not driver
            or not driver.active
        ):
            fail(
                "VALIDATION_ERROR",
                "Use an active owned vehicle and active carrier driver.",
                status=422,
            )
        driver_grant = require(db, driver, ctx.org_id, "shipment.event.record", trade.id)
        if driver_grant.capability != "DRIVER":
            fail("VALIDATION_ERROR", "Select a driver membership.", "driver_user_id", 422)
        declared = vehicle_row.vehicle_json
        if Decimal(declared["declared_payload_capacity_kg"]) < Decimal(
            row.plan_json["declared_gross_weight_kg"]
        ):
            fail("CAPACITY_CONFLICT", "Declared payload capacity is insufficient.", "vehicle_id")
        temperature = "NOT_REQUIRED"
        for item in items(db, row.id):
            cargo = item.cargo_declarations_snapshot
            if (
                cargo.get("hazardous_declared")
                and declared.get("declared_hazardous_capable") is not True
            ):
                fail(
                    "CAPACITY_CONFLICT",
                    "Vehicle lacks declared hazardous capability.",
                    "vehicle_id",
                )
            if cargo.get("temperature_controlled"):
                if (
                    not declared["refrigerated"]
                    or Decimal(declared["temperature_min_c"]) > Decimal(cargo["temperature_min_c"])
                    or Decimal(declared["temperature_max_c"]) < Decimal(cargo["temperature_max_c"])
                ):
                    fail(
                        "CAPACITY_CONFLICT",
                        "Declared temperature range does not cover cargo requirements.",
                        "vehicle_id",
                    )
                temperature = "COMPATIBLE_DECLARED"
        volume = "UNKNOWN"
        if (
            row.plan_json.get("declared_volume_m3") is not None
            and declared.get("declared_volume_capacity_m3") is not None
        ):
            if Decimal(row.plan_json["declared_volume_m3"]) > Decimal(
                declared["declared_volume_capacity_m3"]
            ):
                fail("CAPACITY_CONFLICT", "Declared volume capacity is insufficient.", "vehicle_id")
            volume = "SUFFICIENT_DECLARED"
        for kind, resource in (("VEHICLE", vehicle_row.id), ("DRIVER", driver.id)):
            conflict = db.scalar(
                select(Booking.id).where(
                    Booking.resource_type == kind,
                    Booking.resource_id == resource,
                    Booking.released_at.is_(None),
                    Booking.booking_start_at < assignment.booking_end_at,
                    Booking.booking_end_at > assignment.booking_start_at,
                    Booking.assignment_id != (row.active_assignment_id or uid()),
                )
            )
            if conflict:
                fail(
                    "RESOURCE_BOOKING_CONFLICT",
                    "Vehicle or driver has an overlapping accepted booking.",
                )
        if row.active_assignment_id:
            predecessor = exists(db, Assignment, row.active_assignment_id)
            predecessor.status = "SUPERSEDED"
            touch(predecessor)
            assignment.supersedes_assignment_id = predecessor.id
            for booking in db.scalars(
                select(Booking).where(
                    Booking.assignment_id == predecessor.id, Booking.released_at.is_(None)
                )
            ):
                booking.released_at = now()
            record(db, ctx, "ASSIGNMENT_SUPERSEDED", predecessor, trade, row)
            db.flush()
        assignment.status = "ACCEPTED"
        assignment.vehicle_id, assignment.driver_user_id = vehicle_row.id, driver.id
        assignment.vehicle_snapshot = {"id": vehicle_row.id, **declared}
        assignment.driver_snapshot = {
            "id": driver.id,
            "display_name": driver.display_name,
            "phone_e164": driver.phone_e164,
        }
        assignment.suitability_json = {
            "declared_capacity_result": "SUFFICIENT_DECLARED",
            "declared_temperature_result": temperature,
            "volume_assessment": volume,
            "verification_status": "NOT_ASSESSED",
        }
        row.active_assignment_id = assignment.id
        db.flush()
        for kind, resource in (("VEHICLE", vehicle_row.id), ("DRIVER", driver.id)):
            db.add(
                Booking(
                    assignment_id=assignment.id,
                    resource_type=kind,
                    resource_id=resource,
                    booking_start_at=assignment.booking_start_at,
                    booking_end_at=assignment.booking_end_at,
                )
            )
    assignment.decided_by_user_id, assignment.decided_at = ctx.user.id, now()
    touch(assignment)
    touch(row)
    record(
        db,
        ctx,
        "ASSIGNMENT_DECIDED",
        assignment,
        trade,
        row,
        {"decision": payload.decision, "reason": payload.reason},
    )
    return view(assignment, trade, ctx)
