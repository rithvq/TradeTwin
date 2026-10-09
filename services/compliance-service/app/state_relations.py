"""Versioned operational memory and evidence-backed pre-dispatch route comparisons."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy.orm import Session

from app.auth import require_role
from app.config import settings
from app.database import get_db
from app.document_client import get_uploaded_documents
from app.evaluator import evaluate_compliance
from app.models import QuestionAnswer, RegulationVersion, StateRelationRecord
from app.regulations import load_rules_with_published
from app.regulatory_sources import ensure_source_review
from app.shipment_client import get_shipment_context

router = APIRouter(prefix="/state-relations", tags=["state-relations"])


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state: str = Field(min_length=2, max_length=80)
    city: str = Field(min_length=2, max_length=100)
    pincode: str = Field(pattern=r"^[1-9][0-9]{5}$")
    longitude: float | None = Field(default=None, ge=68, le=98, allow_inf_nan=False)
    latitude: float | None = Field(default=None, ge=6, le=38, allow_inf_nan=False)


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weight: float = Field(gt=0, le=100, allow_inf_nan=False, description="Gross vehicle tonnes")
    height: float = Field(gt=0, le=6, allow_inf_nan=False)
    width: float = Field(gt=0, le=5, allow_inf_nan=False)
    length: float = Field(gt=0, le=40, allow_inf_nan=False)
    axleload: float = Field(gt=0, le=30, allow_inf_nan=False)
    hazmat: bool = False


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reference: str = Field(min_length=2, max_length=80)
    carrier: str = Field(min_length=2, max_length=120)
    places: list[Place] = Field(min_length=2, max_length=12)
    total_price_inr: float = Field(gt=0, le=1e9, allow_inf_nan=False)
    duration_hours: float = Field(gt=0, le=1000, allow_inf_nan=False)
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    source_url: HttpUrl
    source_reference: str = Field(min_length=2, max_length=200)
    review_note: str = Field(min_length=20, max_length=2000)
    vehicle: Vehicle
    coverage_confirmed: bool = False
    all_inclusive: Literal[True]

    @model_validator(mode="after")
    def check_dates(self):
        if self.observed_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Observation cannot be in the future")
        if self.valid_until <= self.observed_at:
            raise ValueError("Expiry must follow observation")
        if (
            self.source_url.scheme != "https"
            or self.source_url.username
            or self.source_url.password
        ):
            raise ValueError("Source reference must be HTTPS without credentials")
        if len({p.pincode for p in self.places}) != len(self.places):
            raise ValueError("Repeated delivery locations are not supported")
        return self


class CompareRequest(BaseModel):
    value_of_time_inr_per_hour: float = Field(default=0, ge=0, le=1e6, allow_inf_nan=False)
    use_observed_history: bool = True


def record_read(row, include_inputs=True):
    result = {
        "id": row.id,
        "kind": row.kind,
        "shipment_id": row.shipment_id,
        "recorded_at": row.created_at.isoformat(),
        **row.payload,
    }
    if not include_inputs:
        result.pop("evidence_inputs", None)
    return result


def append(db, shipment_id, kind, reference, payload):
    row = StateRelationRecord(
        shipment_id=shipment_id, kind=kind, reference=reference, payload=payload
    )
    db.add(row)
    db.flush()
    return row


def shipment_fingerprint(shipment):
    return fingerprint(
        {
            key: shipment.get(key)
            for key in (
                "id",
                "domestic",
                "consignments",
                "planned_departure_at",
                "planned_arrival_at",
                "transport_mode",
            )
        }
    )


def capture_events(db, shipment, events):
    existing = {
        row.reference
        for row in db.query(StateRelationRecord)
        .filter_by(shipment_id=shipment["id"], kind="EVENT")
        .all()
    }
    for event in events:
        reference = fingerprint(event)
        if reference not in existing:
            append(
                db,
                shipment["id"],
                "EVENT",
                reference,
                {"event": event, "shipment_reference": shipment["shipment_reference"]},
            )
            existing.add(reference)


def corridor_history(rows, now=None):
    # Only shipment-level load/arrival observations establish a whole-load travel interval.
    latest = {}
    for row in rows:
        event = row.payload["event"]
        latest[(row.shipment_id, event["id"])] = event
    by_shipment = {}
    for (shipment_id, _), event in latest.items():
        if now and not now - timedelta(days=90) <= timestamp(event["occurred_at"]) <= now:
            continue
        by_shipment.setdefault(shipment_id, []).append(event)
    corridors = {}
    for shipment_id, events in by_shipment.items():
        departure = None
        for event in sorted(events, key=lambda e: timestamp(e["occurred_at"])):
            place = (event.get("metadata") or {}).get("location")
            if not place or event.get("consignment_id"):
                continue
            if event["event_type"] == "LOADED":
                departure = event
            elif event["event_type"] in {"ARRIVED_AT_HUB", "DELIVERED"} and departure:
                origin = departure["metadata"]["location"]
                hours = (
                    timestamp(event["occurred_at"]) - timestamp(departure["occurred_at"])
                ).total_seconds() / 3600
                if origin["pincode"] != place["pincode"] and 0 < hours <= 1000:
                    key = f"{origin['pincode']}:{place['pincode']}"
                    corridors.setdefault(key, []).append(
                        {
                            "hours": hours,
                            "shipment_id": shipment_id,
                            "event_ids": [departure["id"], event["id"]],
                            "observed_at": event["occurred_at"],
                        }
                    )
                departure = None
    return {
        key: {
            "sample_count": len(samples),
            "median_hours": round(median(s["hours"] for s in samples), 2),
            "observations": samples,
        }
        for key, samples in corridors.items()
    }


def require_domestic(shipment):
    if not shipment.get("domestic") or shipment.get("transport_mode") != "ROAD":
        raise HTTPException(422, "State relations currently support domestic road shipments")


def validate_path(shipment, offer):
    places = offer["places"]
    plan = shipment["domestic"]

    def same(left, right):
        return (
            left["pincode"] == right["pincode"]
            and left["state"].casefold() == right["state"].casefold()
        )

    if not same(places[0], plan["origin"]) or not same(places[-1], plan["destination"]):
        raise HTTPException(422, "Offer must preserve shipment origin and final destination")
    for item in shipment["consignments"]:
        if not any(same(p, item["domestic"]["destination"]) for p in places[1:]):
            raise HTTPException(422, "Offer must include every consignment delivery location")


@router.get("/{shipment_id}")
def memory(
    shipment_id: str, db: Session = Depends(get_db), principal=Depends(require_role("viewer"))
):
    shipment, _ = get_shipment_context(shipment_id)
    require_domestic(shipment)
    rows = (
        db.query(StateRelationRecord)
        .filter_by(shipment_id=shipment_id)
        .order_by(StateRelationRecord.created_at.desc())
        .limit(200)
        .all()
    )
    events = (
        db.query(StateRelationRecord)
        .filter_by(kind="EVENT")
        .order_by(StateRelationRecord.created_at.asc())
        .all()
    )
    return {
        "records": [record_read(row, include_inputs=False) for row in rows],
        "corridors": corridor_history(events),
        "routing_configured": bool(settings.ors_api_key and settings.allow_external_routing),
        "catalog_mode": settings.regulation_catalog_mode,
    }


@router.get("/{shipment_id}/decisions/{decision_id}")
def decision_evidence(
    shipment_id: str,
    decision_id: str,
    db: Session = Depends(get_db),
    principal=Depends(require_role("viewer")),
):
    get_shipment_context(shipment_id)
    row = db.get(StateRelationRecord, decision_id)
    if row is None or row.shipment_id != shipment_id or row.kind != "DECISION":
        raise HTTPException(404, "Decision not found")
    return record_read(row)


@router.post("/{shipment_id}/observe")
def observe(
    shipment_id: str, db: Session = Depends(get_db), principal=Depends(require_role("operator"))
):
    shipment, events = get_shipment_context(shipment_id)
    require_domestic(shipment)
    capture_events(db, shipment, events)
    db.commit()
    return {"status": "recorded", "event_count": len(events)}


@router.post("/{shipment_id}/offers")
def add_offer(
    shipment_id: str,
    payload: Offer,
    db: Session = Depends(get_db),
    principal=Depends(require_role("admin")),
):
    shipment, events = get_shipment_context(shipment_id)
    require_domestic(shipment)
    offer = payload.model_dump(mode="json")
    validate_path(shipment, offer)
    offer.update(
        {
            "shipment_fingerprint": shipment_fingerprint(shipment),
            "reviewed_by": principal.actor_id,
            "source_kind": "REVIEWER_ENTERED_CARRIER_QUOTE",
        }
    )
    row = append(db, shipment_id, "OFFER", fingerprint([payload.carrier, payload.reference]), offer)
    capture_events(db, shipment, events)
    db.commit()
    return record_read(row)


@router.post("/{shipment_id}/offers/{offer_id}/refresh-routing")
def refresh_routing(
    shipment_id: str,
    offer_id: str,
    db: Session = Depends(get_db),
    principal=Depends(require_role("operator")),
):
    shipment, _ = get_shipment_context(shipment_id)
    row = db.get(StateRelationRecord, offer_id)
    if row is None or row.shipment_id != shipment_id or row.kind != "OFFER":
        raise HTTPException(404, "Offer not found")
    if not settings.allow_external_routing or not settings.ors_api_key:
        raise HTTPException(
            503, "Truck routing requires an API key and explicit external-routing consent"
        )
    offer = row.payload
    if offer["shipment_fingerprint"] != shipment_fingerprint(shipment):
        raise HTTPException(409, "Shipment changed; obtain a revised quote")
    if any(p.get("longitude") is None or p.get("latitude") is None for p in offer["places"]):
        raise HTTPException(422, "Provide verified coordinates for every stop")
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv/json"
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.post(
                url,
                headers={"Authorization": settings.ors_api_key},
                json={
                    "coordinates": [[p["longitude"], p["latitude"]] for p in offer["places"]],
                    "instructions": False,
                    "geometry": False,
                    "options": {
                        "vehicle_type": "hgv",
                        "avoid_borders": "all",
                        "profile_params": {"restrictions": offer["vehicle"]},
                    },
                },
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
            distance = float(route["summary"]["distance"]) / 1000
            hours = float(route["summary"]["duration"]) / 3600
            if not 0 < distance <= 20000 or not 0 < hours <= 1000:
                raise ValueError("Invalid routing values")
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        raise HTTPException(
            502, "Routing provider unavailable or invalid; prior snapshots retained"
        ) from exc
    result = append(
        db,
        shipment_id,
        "ROUTING",
        offer_id,
        {
            "offer_id": offer_id,
            "distance_km": distance,
            "driving_hours": hours,
            "source_url": url,
            "source_kind": "OPENROUTESERVICE_HGV_ESTIMATE",
            "valid_until": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            "response_hash": fingerprint(response.json()),
            "warnings": route.get("warnings", []),
            "note": "Map-based truck estimate, not live traffic, freight price or legal clearance",
        },
    )
    db.commit()
    return record_read(result)


def compare(
    shipment, events, documents, rules, answers, offers, routing, history, preferences, now
):
    options = []
    departure = timestamp(shipment["planned_departure_at"])
    for row in offers:
        offer = row.payload
        blocks = []
        try:
            validate_path(shipment, offer)
        except HTTPException as exc:
            blocks.append(exc.detail)
        if offer["shipment_fingerprint"] != shipment_fingerprint(shipment):
            blocks.append("Shipment or cargo changed since quotation")
        if timestamp(offer["valid_until"]) < max(now, departure):
            blocks.append("Quote expired before booking or planned departure")
        if not offer["coverage_confirmed"]:
            blocks.append("Carrier capacity, road restrictions and charge coverage need review")
        if departure < now or any(e["event_type"] != "CREATED" for e in events):
            blocks.append(
                "Pre-dispatch planning only; an in-progress movement requires an amendment"
            )
        candidate = deepcopy(shipment)
        candidate["route_legs"] = [
            {
                "sequence_number": i + 1,
                "origin_country": "India",
                "destination_country": "India",
                "transport_mode": "ROAD",
                "carrier_name": offer["carrier"],
                "domestic": {"origin": a, "destination": b},
            }
            for i, (a, b) in enumerate(zip(offer["places"], offer["places"][1:], strict=False))
        ]
        assessment = evaluate_compliance(
            candidate, events, documents, rules, answers=answers, as_of=departure.date()
        )
        if assessment.status != "COMPLIANT":
            blocks.append("Compliance evidence unresolved: " + assessment.recommended_action)
        route = routing.get(row.id)
        provider_hours = None
        if route:
            if timestamp(route.payload["valid_until"]) < now:
                blocks.append("Previously fetched truck routing is stale; refresh it")
            elif route.payload["warnings"]:
                blocks.append("Truck routing returned warnings requiring review")
            else:
                provider_hours = route.payload["driving_hours"]
        lanes = [
            history.get(f"{a['pincode']}:{b['pincode']}")
            for a, b in zip(offer["places"], offer["places"][1:], strict=False)
        ]
        historical_hours = (
            sum(lane["median_hours"] for lane in lanes)
            if lanes and all(lane and lane["sample_count"] >= 3 for lane in lanes)
            else None
        )
        hours = max(
            offer["duration_hours"],
            provider_hours or 0,
            (historical_hours or 0) if preferences.use_observed_history else 0,
        )
        if departure + timedelta(hours=hours) > timestamp(shipment["planned_arrival_at"]):
            blocks.append("Estimated arrival exceeds the planned deadline")
        generalized = offer["total_price_inr"] + hours * preferences.value_of_time_inr_per_hour
        options.append(
            {
                "offer_id": row.id,
                "carrier": offer["carrier"],
                "reference": offer["reference"],
                "places": offer["places"],
                "quoted_price_inr": offer["total_price_inr"],
                "duration_hours": round(hours, 2),
                "historical_hours": historical_hours,
                "routing_snapshot_id": route.id if route else None,
                "corridor_history": lanes,
                "generalized_cost_inr": round(generalized, 2),
                "blocking_reasons": blocks,
                "eligible": not blocks,
                "compliance": assessment.model_dump(mode="json"),
                "source_url": offer["source_url"],
                "source_reference": offer["source_reference"],
                "observed_at": offer["observed_at"],
                "valid_until": offer["valid_until"],
                "review_note": offer["review_note"],
                "source_kind": offer["source_kind"],
                "explanation": "All-inclusive quote + chosen INR/hour x conservative duration. "
                "Duration is the maximum of carrier duration, fresh routing estimate and "
                "optional historical medians (at least three samples per leg). "
                "No synthetic risk markup.",
            }
        )
    options.sort(key=lambda o: (not o["eligible"], o["generalized_cost_inr"], o["offer_id"]))
    best = next((o for o in options if o["eligible"]), None)
    return {
        "options": options,
        "recommended_offer_id": best["offer_id"] if best else None,
        "scope": "Best-supported supplied offer, not a global optimum or booking guarantee",
        "unknown_factors": ["Live traffic", "Unreported road closures", "Unquoted price changes"],
        "preferences": preferences.model_dump(),
        "engine_version": "state-relations-1",
    }


@router.post("/{shipment_id}/evaluate")
def evaluate(
    shipment_id: str,
    payload: CompareRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_role("operator")),
):
    shipment, events = get_shipment_context(shipment_id)
    require_domestic(shipment)
    documents = get_uploaded_documents(shipment_id)
    rules = load_rules_with_published(db)
    answers = {
        row.attribute_key: row.answer
        for row in db.query(QuestionAnswer)
        .filter_by(shipment_id=shipment_id)
        .order_by(QuestionAnswer.created_at.asc())
        .all()
    }
    capture_events(db, shipment, events)
    rows = (
        db.query(StateRelationRecord)
        .filter_by(shipment_id=shipment_id)
        .order_by(StateRelationRecord.created_at.asc())
        .all()
    )
    latest_offers = {row.reference: row for row in rows if row.kind == "OFFER"}
    if len(latest_offers) > 30:
        raise HTTPException(422, "Comparison is limited to 30 current offer references")
    routing = {row.reference: row for row in rows if row.kind == "ROUTING"}
    observations = (
        db.query(StateRelationRecord)
        .filter_by(kind="EVENT")
        .order_by(StateRelationRecord.created_at.asc())
        .all()
    )
    history = corridor_history(observations, datetime.now(UTC))
    result = compare(
        shipment,
        events,
        documents,
        rules,
        answers,
        list(latest_offers.values()),
        routing,
        history,
        payload,
        datetime.now(UTC),
    )
    if settings.regulation_catalog_mode != "reviewed":
        result["recommended_offer_id"] = None
        for option in result["options"]:
            option["eligible"] = False
            option["blocking_reasons"].append(
                "Demo regulation catalog is not a reviewed planning basis"
            )
    for option in result["options"]:
        for rule in option["compliance"]["applicable_rules"]:
            version = (
                db.query(RegulationVersion)
                .filter_by(rule_id=rule["rule_id"], version=rule["version"], status="PUBLISHED")
                .first()
            )
            if version:
                try:
                    ensure_source_review(db, version.id)
                except HTTPException:
                    option["eligible"] = False
                    option["blocking_reasons"].append(
                        f"Regulation source changed, is stale or lacks review: {rule['rule_id']}"
                    )
    eligible = [option for option in result["options"] if option["eligible"]]
    result["recommended_offer_id"] = eligible[0]["offer_id"] if eligible else None
    inputs = {
        "shipment": shipment,
        "events": events,
        "documents": [
            {
                "document_id": d.document_id,
                "document_type": d.document_type,
                "consignment_id": d.consignment_id,
                "jurisdiction": d.jurisdiction,
                "metadata": {"verification_status": d.metadata.get("verification_status")},
            }
            for d in documents
        ],
        "rules": [r.model_dump(mode="json") for r in rules],
        "answers": answers,
        "offers": [record_read(o) for o in latest_offers.values()],
        "routing": [record_read(r) for r in routing.values()],
        "history": history,
        "preferences": payload.model_dump(),
    }
    previous = next((row for row in reversed(rows) if row.kind == "DECISION"), None)
    result["evaluation_fingerprint"] = fingerprint(result)
    if (
        previous
        and previous.payload.get("evaluation_fingerprint") == result["evaluation_fingerprint"]
        and previous.payload["input_fingerprint"] == fingerprint(inputs)
    ):
        db.commit()
        return record_read(previous)
    result.update(
        {
            "input_fingerprint": fingerprint(inputs),
            "catalog_mode": settings.regulation_catalog_mode,
            "actor_id": principal.actor_id,
            "previous_decision_id": previous.id if previous else None,
            "inputs_changed": previous is None
            or previous.payload["input_fingerprint"] != fingerprint(inputs),
            "evidence_inputs": inputs,
        }
    )
    row = append(db, shipment_id, "DECISION", fingerprint(inputs), result)
    db.commit()
    return record_read(row)
