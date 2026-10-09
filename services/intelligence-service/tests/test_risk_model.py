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
from app import llm_gateway


def test_domestic_prediction_uses_domestic_features_and_explicit_synthetic_version():
    shipment = {
        "domestic": {"origin": {"state": "Tamil Nadu"}},
        "consignments": [{"domestic": {"consignment_value": 75000}, "proposed_hs_code": "620520"}],
        "route_legs": [{"domestic": {"distance_km": 350}}],
    }
    result = score_shipment(shipment, [])
    assert result["model_version"] == "domestic-synthetic-v1"
    assert "includes_uae" not in result["features"]
    assert result["features"]["distance_km"] == 350
    assert "unvalidated" in result["warning"]
    assert 0 <= result["inspection_probability"] <= 1


def test_synthetic_risk_model_returns_warning_probabilities_and_factors() -> None:
    result = score_shipment(sample_shipment(), sample_events())

    assert result["warning"] == WARNING
    assert 0 <= result["inspection_probability"] <= 1
    assert 0 <= result["rejection_probability"] <= 1
    assert result["expected_clearance_delay_hours"] > 0
    assert result["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert any(factor["factor"] == "Lithium battery cargo" for factor in result["risk_factors"])


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


def test_private_text_never_sent_without_opt_in(monkeypatch):
    monkeypatch.setattr(llm_gateway.settings, "allow_private_data_llm", False)
    monkeypatch.setattr(llm_gateway.settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(llm_gateway.settings, "llm_api_key", "test-not-a-real-key")

    def unexpected_request(*args, **kwargs):
        raise AssertionError("Private text must not leave the deployment")

    monkeypatch.setattr(llm_gateway.httpx, "post", unexpected_request)
    assert isinstance(llm_gateway.get_gateway(), llm_gateway.MockLLMGateway)
    assert llm_gateway.OpenAICompatibleGateway().classification_hints("phone", "confidential")
