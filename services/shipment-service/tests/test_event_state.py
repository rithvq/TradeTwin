import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["NEO4J_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def test_uae_unloading_updates_consignment_destination_states() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    now = datetime.now(UTC).replace(microsecond=0)
    with TestClient(app) as client:
        shipment_response = client.post(
            "/shipments",
            json={
                "shipment_reference": "TT-TEST-IND-UAE-DEU",
                "exporter_country": "India",
                "importer_country": "Germany",
                "transport_mode": "SEA",
                "planned_departure_at": now.isoformat(),
                "planned_arrival_at": (now + timedelta(days=21)).isoformat(),
                "consignments": [
                    {
                        "product_name": "Lithium batteries",
                        "product_description": "Rechargeable lithium batteries.",
                        "quantity": 120,
                        "declared_value": "18000.00",
                        "currency": "USD",
                        "country_of_origin": "India",
                        "destination_country": "Germany",
                    },
                    {
                        "product_name": "Consumer electronics",
                        "product_description": "Packaged consumer electronics.",
                        "quantity": 240,
                        "declared_value": "32000.00",
                        "currency": "USD",
                        "country_of_origin": "India",
                        "destination_country": "UAE",
                    },
                ],
                "route_legs": [
                    {
                        "sequence_number": 1,
                        "origin_country": "India",
                        "destination_country": "UAE",
                        "transport_mode": "SEA",
                        "carrier_name": "TradeTwin Demo Line",
                    },
                    {
                        "sequence_number": 2,
                        "origin_country": "UAE",
                        "destination_country": "Germany",
                        "transport_mode": "SEA",
                        "carrier_name": "TradeTwin Demo Line",
                    },
                ],
            },
        )
        assert shipment_response.status_code == 201

        shipment = shipment_response.json()
        shipment_id = shipment["id"]
        consignments = {item["product_name"]: item for item in shipment["consignments"]}

        for consignment in consignments.values():
            event_response = client.post(
                f"/shipments/{shipment_id}/events",
                json={
                    "consignment_id": consignment["id"],
                    "event_type": "LOADED",
                    "location_country": "India",
                    "occurred_at": (now + timedelta(hours=1)).isoformat(),
                    "metadata": {"test": True},
                },
            )
            assert event_response.status_code == 201

        transit_response = client.post(
            f"/shipments/{shipment_id}/events",
            json={
                "event_type": "ARRIVED_AT_TRANSIT_PORT",
                "location_country": "UAE",
                "occurred_at": (now + timedelta(days=7)).isoformat(),
                "metadata": {"test": True},
            },
        )
        assert transit_response.status_code == 201

        unload_response = client.post(
            f"/shipments/{shipment_id}/events",
            json={
                "consignment_id": consignments["Consumer electronics"]["id"],
                "event_type": "UNLOADED",
                "location_country": "UAE",
                "occurred_at": (now + timedelta(days=7, hours=2)).isoformat(),
                "metadata": {"test": True},
            },
        )
        assert unload_response.status_code == 201

        detail_response = client.get(f"/shipments/{shipment_id}")
        assert detail_response.status_code == 200
        states = {
            item["product_name"]: item["customs_status"]
            for item in detail_response.json()["consignments"]
        }

        assert states["Consumer electronics"] == "UAE_IMPORT"
        assert states["Lithium batteries"] == "UAE_TRANSIT"

        graph_response = client.get(f"/shipments/{shipment_id}/graph")
        assert graph_response.status_code == 200
        graph = graph_response.json()
        assert any(node["type"] == "Shipment" for node in graph["nodes"])
        assert any(edge["label"] == "AFFECTS_CONSIGNMENT" for edge in graph["edges"])


def test_delete_shipment_removes_it_from_list_and_detail() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    now = datetime.now(UTC).replace(microsecond=0)
    with TestClient(app) as client:
        shipment_response = client.post(
            "/shipments",
            json={
                "shipment_reference": "TT-DELETE-TEST",
                "exporter_country": "India",
                "importer_country": "Germany",
                "transport_mode": "SEA",
                "planned_departure_at": now.isoformat(),
                "planned_arrival_at": (now + timedelta(days=14)).isoformat(),
                "consignments": [
                    {
                        "product_name": "Lithium batteries",
                        "product_description": "Rechargeable lithium batteries.",
                        "quantity": 12,
                        "declared_value": "1800.00",
                        "currency": "USD",
                        "country_of_origin": "India",
                        "destination_country": "Germany",
                    }
                ],
                "route_legs": [],
            },
        )
        assert shipment_response.status_code == 201
        shipment_id = shipment_response.json()["id"]

        delete_response = client.delete(f"/shipments/{shipment_id}")
        assert delete_response.status_code == 204

        detail_response = client.get(f"/shipments/{shipment_id}")
        assert detail_response.status_code == 404

        list_response = client.get("/shipments")
        references = [item["shipment_reference"] for item in list_response.json()]
        assert "TT-DELETE-TEST" not in references
