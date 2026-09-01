# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.risk_model import WARNING, score_shipment


def test_synthetic_risk_model_returns_warning_probabilities_and_factors() -> None:
    result = score_shipment(sample_shipment(), sample_events())

    assert result["warning"] == WARNING
    assert 0 <= result["inspection_probability"] <= 1
    assert 0 <= result["rejection_probability"] <= 1
    assert result["expected_clearance_delay_hours"] > 0
    assert result["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert any(
        factor["factor"] == "Lithium battery cargo"
        for factor in result["risk_factors"]
    )


def sample_shipment() -> dict:
    return {
        "id": "shipment-demo",
        "shipment_reference": "TT-DEMO-IND-UAE-DEU",
        "exporter_country": "India",
        "importer_country": "Germany",
        "transport_mode": "SEA",
        "consignments": [
            {
                "id": "consignment-lithium",
                "product_name": "Lithium batteries",
                "product_description": "Rechargeable lithium battery packs.",
                "quantity": 120,
                "declared_value": "18000.00",
                "country_of_origin": "India",
                "destination_country": "Germany",
                "proposed_hs_code": None,
            },
            {
                "id": "consignment-electronics",
                "product_name": "Consumer electronics",
                "product_description": "Packaged consumer electronics.",
                "quantity": 240,
                "declared_value": "32000.00",
                "country_of_origin": "India",
                "destination_country": "UAE",
                "proposed_hs_code": None,
            },
        ],
        "route_legs": [
            {
                "id": "leg-1",
                "sequence_number": 1,
                "origin_country": "India",
                "destination_country": "UAE",
            },
            {
                "id": "leg-2",
                "sequence_number": 2,
                "origin_country": "UAE",
                "destination_country": "Germany",
            },
        ],
    }


def sample_events() -> list[dict]:
    return [
        {
            "id": "event-arrived-uae",
            "event_type": "ARRIVED_AT_TRANSIT_PORT",
            "location_country": "UAE",
            "consignment_id": None,
        },
        {
            "id": "event-unloaded-electronics",
            "event_type": "UNLOADED",
            "location_country": "UAE",
            "consignment_id": "consignment-electronics",
        },
    ]
