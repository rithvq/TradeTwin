"""Minimal captured planning inputs; no PDF, identities, API credential or private quote export."""

from decimal import Decimal

from app.compliance import context as compliance_context
from app.compliance import governance
from app.compliance.clock import aware, instant
from app.compliance.models import Binding, Source
from app.corridor.models import Incident
from app.corridor.projection import capture as corridor_capture
from app.freight.access import base_context
from app.freight.models import Dataset, Location, Profile
from app.freight.routing import dataset_current
from app.operations.access import exists, fail
from app.operations.models import Assignment, Vehicle
from app.trades.reference import STATES
from app.trades.terms import digest

from . import history


def confirmed_pin(location):
    return bool(
        location
        and location.precision == "CONFIRMED_LOADING_GATE"
        and location.location_json.get("state_coordinate_conflict_resolved")
    )


def nominated_truck(db, cn):
    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    vehicle = db.get(Vehicle, assignment.vehicle_id) if assignment else None
    row = (
        db.get(Profile, vehicle.current_routing_profile_revision_id)
        if vehicle and vehicle.current_routing_profile_revision_id
        else None
    )
    if not row:
        return None
    data = row.profile_json
    required = (
        "overall_height_mm",
        "overall_width_mm",
        "overall_length_mm",
        "combined_tare_weight_kg",
        "maximum_actual_axle_load_kg",
    )
    if any(data.get(key) is None for key in required):
        return None
    return {
        "height_m": str(Decimal(data["overall_height_mm"]) / 1000),
        "width_m": str(Decimal(data["overall_width_mm"]) / 1000),
        "length_m": str(Decimal(data["overall_length_mm"]) / 1000),
        "tare_kg": str(data["combined_tare_weight_kg"]),
        "axle_load_kg": str(data["maximum_actual_axle_load_kg"]),
        "maximum_loaded_kg": data.get("maximum_authorised_combined_weight_kg"),
    }


def permits(db, cn, at):
    from types import SimpleNamespace

    from app.freight.runs import permit_snapshot

    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    if not assignment:
        return {"covered_states": [], "valid_until": None, "basis": "No accepted assignment"}
    head = compliance_context.heads(db, cn)
    binding = (
        db.get(Binding, head.current_binding_revision_id)
        if head and head.current_binding_revision_id
        else None
    )
    refs = binding.binding_json.get("transport_evidence_revision_ids", []) if binding else []
    quote = SimpleNamespace(
        vehicle_id=assignment.vehicle_id,
        quote_json={
            "transport_evidence_revision_ids": refs,
            "vehicle_snapshot": assignment.vehicle_snapshot,
        },
    )
    from datetime import timedelta

    result = permit_snapshot(db, quote, at + timedelta(seconds=1), at)
    return {
        "covered_states": result.get("covered_states", []),
        "valid_until": min((r["valid_until"] for r in result.get("source_refs", [])), default=None),
        "basis": "Existing reviewed nominated-vehicle permit checks; "
        "exact source currency and service validity still apply.",
    }


def capture(db, ctx, trade, cn, payload):
    at = instant(db)
    base = base_context(db, trade, cn)
    pins = []
    for role in ("pickup", "drop"):
        ident = base[role + "_location_revision_id"]
        if not ident:
            fail(
                "ROUTING_INPUT_MISSING", "Confirm pickup and drop gates in freight planning first."
            )
        location = exists(db, Location, ident)
        if not confirmed_pin(location):
            fail(
                "ROUTING_INPUT_MISSING",
                "Use confirmed loading gates with resolved state coordinates.",
            )
        pins.append(
            {
                "id": location.id,
                "coordinates": [float(location.longitude), float(location.latitude)],
                "state_code": location.state_code,
            }
        )
    truck = payload.truck.model_dump(mode="json") if payload.truck else nominated_truck(db, cn)
    if not truck:
        fail(
            "ROUTING_INPUT_MISSING",
            "Supply truck dimensions, tare and actual axle load, "
            "or prepare the assigned truck profile.",
        )
    cargo = base["cargo_snapshot"]
    if truck.get("maximum_loaded_kg") and Decimal(truck["tare_kg"]) + Decimal(
        cargo["gross_weight_kg"]
    ) > Decimal(truck["maximum_loaded_kg"]):
        fail(
            "ROUTE_TRUCK_OVERWEIGHT",
            "The declared loaded weight exceeds the truck's authorized maximum.",
        )
    packs, registry, boundary = governance.resolve(db, trade.execution_mode, payload.departure_at)
    projection = corridor_capture(
        db,
        trade,
        cn,
        route={
            "state_sequence": list(STATES),
            "ordered_edge_keys": [],
            "dataset_revision_id": None,
        },
        at=at,
    )
    projection = {
        key: value
        for key, value in projection.items()
        if key not in {"valid_until", "evaluated_as_of"}
    }
    for event in projection["events"]:
        incident = db.get(Incident, event["incident_id"])
        event["public_geometry"] = bool(incident and incident.visibility == "PUBLIC_APPROVED")
    sources = [
        db.get(Source, ident)
        for ident in sorted({ident for pack in packs for ident in pack.source_ids})
    ]
    policy = {
        "registry": registry,
        "supported_corridors": [
            seq for pack in packs for seq in pack.policy_json.get("supported_corridors", [])
        ],
        "packs": [
            {
                "id": p.id,
                "version": p.version,
                "title": p.title,
                "valid_until": aware(p.effective_until).isoformat() if p.effective_until else None,
            }
            for p in packs
        ],
        "sources": [
            {
                "id": s.id,
                "title": s.title,
                "url": s.official_url,
                "sha256": s.source_sha256,
                "recorded_at": aware(s.created_at).isoformat(),
            }
            for s in sources
            if s
        ],
    }
    dataset = None
    if payload.dataset_revision_id:
        row = exists(db, Dataset, payload.dataset_revision_id)
        if row.execution_mode != trade.execution_mode or not dataset_current(db, row, at):
            fail("ROUTE_SOURCE_STALE", "Select a current published dataset in this trade's mode.")
        dataset = {"id": row.id, "data": row.dataset_json, "hash": row.content_hash}
    result = {
        "context_hash": base["planning_context_hash"],
        "consignment_id": cn.id,
        "movement_status": cn.movement_status,
        "planning_status": cn.planning_status,
        "active_assignment_id": cn.active_assignment_id,
        "execution_mode": trade.execution_mode,
        "request": payload.model_dump(mode="json"),
        "pickup": pins[0],
        "drop": pins[1],
        "truck": truck,
        "profile_codes": [],
        "cargo_weight_kg": str(cargo["gross_weight_kg"]),
        "hazardous_declared": any(i["cargo"].get("hazardous_declared") for i in cargo["items"]),
        "permit_coverage": permits(db, cn, at)
        if not payload.truck
        else {
            "covered_states": [],
            "valid_until": None,
            "basis": "User-declared truck; vehicle-bound permits are not transferable.",
        },
        "policy": policy,
        "corridor": projection,
        "history": history.capture(db, ctx, trade.execution_mode, at),
        "dataset": dataset,
        "policy_boundary": boundary.isoformat() if boundary else None,
    }
    if not payload.truck and cn.active_assignment_id:
        assignment = db.get(Assignment, cn.active_assignment_id)
        vehicle = db.get(Vehicle, assignment.vehicle_id)
        profile = (
            db.get(Profile, vehicle.current_routing_profile_revision_id)
            if (vehicle and vehicle.current_routing_profile_revision_id)
            else None
        )
        result["profile_codes"] = (
            profile.profile_json.get("supported_cargo_profile_codes", []) if profile else []
        )
    result["dependency_hash"] = digest(result)
    return result
