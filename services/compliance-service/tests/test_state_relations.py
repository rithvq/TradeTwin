# ruff: noqa: E402, I001
import os
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app import state_relations as sr
from app.auth import Principal
from app.database import Base
from app.schemas import ComplianceRule

NOW = datetime(2026, 9, 14, tzinfo=UTC)
A = {"state": "Tamil Nadu", "city": "Chennai", "pincode": "600001"}
B = {"state": "Karnataka", "city": "Bengaluru", "pincode": "560001"}
C = {"state": "Maharashtra", "city": "Pune", "pincode": "411001"}


def shipment():
    return {
        "id": "shipment",
        "shipment_reference": "test",
        "transport_mode": "ROAD",
        "planned_departure_at": (NOW + timedelta(days=1)).isoformat(),
        "planned_arrival_at": (NOW + timedelta(days=4)).isoformat(),
        "domestic": {
            "origin": A,
            "destination": C,
            "registered_consignor": True,
            "ordinary_goods": True,
            "movement_reason": "SUPPLY",
        },
        "consignments": [
            {
                "id": "a",
                "product_name": "shirts",
                "domestic": {"destination": C, "consignment_value": 10000},
            },
            {
                "id": "b",
                "product_name": "books",
                "domestic": {"destination": B, "consignment_value": 1000},
            },
        ],
    }


def rule():
    return ComplianceRule(
        rule_id="test",
        title="Fixture only",
        jurisdiction="India",
        procedure_type="domestic",
        effective_from="2026-01-01",
        source_url="https://example.com",
        version="1",
        conditions={"scope": "india_domestic"},
        required_documents=[],
        outcome_if_failed={
            "status": "CONDITIONALLY_COMPLIANT",
            "violation": "Missing",
            "recommended_action": "Upload",
        },
    )


def offer(id="offer", price=1000, hours=12):
    return SimpleNamespace(
        id=id,
        payload={
            "reference": id,
            "carrier": "Test Carrier",
            "places": [A, B, C],
            "total_price_inr": price,
            "duration_hours": hours,
            "observed_at": NOW.isoformat(),
            "valid_until": (NOW + timedelta(days=2)).isoformat(),
            "coverage_confirmed": True,
            "shipment_fingerprint": sr.shipment_fingerprint(shipment()),
            "source_url": "https://example.com/quote",
            "source_reference": "Test quote",
            "review_note": "Reviewed fixture only; not a real price",
            "source_kind": "REVIEWER_ENTERED_CARRIER_QUOTE",
        },
    )


def compare(offers, **kwargs):
    return sr.compare(
        kwargs.get("shipment", shipment()),
        kwargs.get("events", []),
        [],
        kwargs.get("rules", [rule()]),
        {},
        offers,
        kwargs.get("routing", {}),
        kwargs.get("history", {}),
        sr.CompareRequest(value_of_time_inr_per_hour=kwargs.get("time_value", 0)),
        NOW,
    )


def test_price_time_tradeoff_and_explanations():
    cheap = offer("cheap", 1000, 30)
    fast = offer("fast", 1500, 10)
    assert compare([cheap, fast])["recommended_offer_id"] == "cheap"
    result = compare([cheap, fast], time_value=100)
    assert result["recommended_offer_id"] == "fast"
    assert result["options"][0]["generalized_cost_inr"] == 2500
    assert result["options"][0]["source_reference"] == "Test quote"


def test_expired_quotes_missing_delivery_and_changed_cargo_rejected():
    expired = offer("expired", 1)
    expired.payload["valid_until"] = NOW.isoformat()
    incomplete = offer("incomplete", 1)
    incomplete.payload["places"] = [A, C]
    assert compare([expired, incomplete])["recommended_offer_id"] is None
    changed = shipment()
    changed["consignments"][0]["quantity"] = 999
    assert compare([offer()], shipment=changed)["recommended_offer_id"] is None


def test_missing_rules_stale_routing_and_inflight_do_not_pass():
    assert compare([offer()], rules=[])["recommended_offer_id"] is None
    routing = {
        "offer": SimpleNamespace(
            id="route",
            payload={"valid_until": NOW.isoformat(), "warnings": [], "driving_hours": 20},
        )
    }
    routing["offer"].payload["valid_until"] = (NOW - timedelta(seconds=1)).isoformat()
    assert compare([offer()], routing=routing)["recommended_offer_id"] is None
    assert (
        compare([offer()], events=[{"event_type": "LOADED", "id": "loaded"}])[
            "recommended_offer_id"
        ]
        is None
    )


def test_event_memory_deduplicates_revisions_and_history_changes_cost():
    rows = []
    for i in range(3):
        for id, kind, location, hours in [
            ("load", "LOADED", A, 0),
            ("arrive", "ARRIVED_AT_HUB", B, 24),
        ]:
            rows.append(
                SimpleNamespace(
                    shipment_id=str(i),
                    payload={
                        "event": {
                            "id": id,
                            "event_type": kind,
                            "metadata": {"location": location},
                            "occurred_at": (NOW + timedelta(hours=hours)).isoformat(),
                        }
                    },
                )
            )
    history = sr.corridor_history(rows + rows)
    assert history["600001:560001"]["sample_count"] == 3
    assert history["600001:560001"]["median_hours"] == 24
    history["560001:411001"] = {"sample_count": 3, "median_hours": 25}
    result = compare([offer()], history=history, time_value=10)
    assert result["options"][0]["duration_hours"] == 49
    assert result["options"][0]["generalized_cost_inr"] == 1490
    assert sr.timestamp("2026-09-14T05:30:00+05:30") == NOW


def test_decision_history_is_persistent_and_demo_cannot_recommend(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(sr, "get_shipment_context", lambda id: (shipment(), []))
    monkeypatch.setattr(sr, "get_uploaded_documents", lambda id: [])
    monkeypatch.setattr(sr, "load_rules_with_published", lambda db: [rule()])
    monkeypatch.setattr(sr.settings, "regulation_catalog_mode", "demo")
    with Session(engine) as db:
        o = offer()
        sr.append(db, "shipment", "OFFER", "carrier:quote", o.payload)
        db.commit()
        first = sr.evaluate("shipment", sr.CompareRequest(), db, Principal("test", "operator"))
        assert first["recommended_offer_id"] is None
        second = sr.evaluate("shipment", sr.CompareRequest(), db, Principal("test", "operator"))
        assert second["id"] == first["id"]
        revised = deepcopy(o.payload)
        revised["total_price_inr"] = 2000
        sr.append(db, "shipment", "OFFER", "carrier:quote", revised)
        db.commit()
        third = sr.evaluate("shipment", sr.CompareRequest(), db, Principal("test", "operator"))
        assert third["id"] != first["id"]
        assert third["previous_decision_id"] == first["id"]
        assert third["inputs_changed"]
        assert len(third["options"]) == 1
    engine.dispose()


def test_external_routing_requires_consent_and_preserves_records(monkeypatch):
    monkeypatch.setattr(sr, "get_shipment_context", lambda id: (shipment(), []))
    monkeypatch.setattr(sr.settings, "allow_external_routing", False)
    row = SimpleNamespace(shipment_id="shipment", kind="OFFER", payload={})
    db = SimpleNamespace(get=lambda *args: row)
    with pytest.raises(HTTPException) as error:
        sr.refresh_routing("shipment", "offer", db, Principal("test", "operator"))
    assert error.value.status_code == 503


def test_truck_provider_contract_and_failure_do_not_invent_prices(monkeypatch):
    monkeypatch.setattr(sr, "get_shipment_context", lambda id: (shipment(), []))
    monkeypatch.setattr(sr.settings, "allow_external_routing", True)
    monkeypatch.setattr(sr.settings, "ors_api_key", "test-key-not-real")
    payload = offer().payload
    payload["vehicle"] = {
        "weight": 12,
        "height": 3,
        "width": 2.5,
        "length": 8,
        "axleload": 6,
        "hazmat": False,
    }
    payload["places"] = [{**p, "longitude": 77, "latitude": 13} for p in [A, B, C]]
    row = SimpleNamespace(shipment_id="shipment", kind="OFFER", payload=payload)
    recorded = []
    db = SimpleNamespace(get=lambda *args: row, commit=lambda: None)

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert "driving-hgv" in url
            assert set(kwargs["json"]) == {"coordinates", "instructions", "geometry", "options"}
            assert kwargs["json"]["options"]["profile_params"]["restrictions"]["weight"] == 12
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "routes": [{"summary": {"distance": 500000, "duration": 36000}, "warnings": []}]
                },
            )

    monkeypatch.setattr(sr.httpx, "Client", Client)

    def append(db, shipment_id, kind, reference, payload):
        recorded.append(payload)
        return SimpleNamespace(
            id="route", kind=kind, shipment_id=shipment_id, created_at=NOW, payload=payload
        )

    monkeypatch.setattr(sr, "append", append)
    result = sr.refresh_routing("shipment", "offer", db, Principal("test", "operator"))
    assert result["distance_km"] == 500
    assert result["driving_hours"] == 10
    assert "total_price_inr" not in recorded[0]

    def failed(*args, **kwargs):
        raise sr.httpx.ConnectError("offline")

    monkeypatch.setattr(Client, "post", failed)
    with pytest.raises(HTTPException) as error:
        sr.refresh_routing("shipment", "offer", db, Principal("test", "operator"))
    assert error.value.status_code == 502
    assert len(recorded) == 1
