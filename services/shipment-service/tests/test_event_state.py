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

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.domestic import migrate_domestic  # noqa: E402
from app.main import app  # noqa: E402
from app.models import GraphSyncTask  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def test_domestic_migration_preserves_legacy_rows_and_is_idempotent():
    isolated = create_engine("sqlite+pysqlite:///:memory:")
    with isolated.begin() as connection:
        connection.execute(text("CREATE TABLE shipments (id TEXT PRIMARY KEY, reference TEXT)"))
        connection.execute(text("INSERT INTO shipments VALUES ('legacy', 'old-reference')"))
    migrate_domestic(isolated)
    migrate_domestic(isolated)
    with isolated.connect() as connection:
        row = connection.execute(text("SELECT reference, domestic FROM shipments")).one()
        assert row == ("old-reference", None)
    isolated.dispose()


def test_graph_updates_and_deletions_retry_after_outage(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        graph = app.state.graph
        monkeypatch.setattr(graph, "sync_shipment", lambda shipment: False)
        shipment = client.post("/demo/seed").json()
        with SessionLocal() as db:
            assert db.get(GraphSyncTask, shipment["id"]) is not None
        assert client.get("/ready").status_code == 503
        monkeypatch.setattr(graph, "sync_shipment", lambda shipment: True)
        assert client.get("/ready").status_code == 200
        with SessionLocal() as db:
            assert db.get(GraphSyncTask, shipment["id"]) is None

        monkeypatch.setattr(graph, "delete_shipment", lambda shipment_id: False)
        assert client.delete(f"/shipments/{shipment['id']}").status_code == 204
        assert client.get("/ready").status_code == 503
        monkeypatch.setattr(graph, "delete_shipment", lambda shipment_id: True)
        assert client.get("/ready").status_code == 200
        with SessionLocal() as db:
            assert db.get(GraphSyncTask, shipment["id"]) is None


def demo(client):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    response = client.post("/demo/seed")
    assert response.status_code == 200, response.text
    return response.json()


def test_domestic_demo_is_idempotent_and_deliveries_are_independent():
    with TestClient(app) as client:
        shipment = demo(client)
        assert client.post("/demo/seed").json()["id"] == shipment["id"]
        assert shipment["shipment_reference"] == "TT-DEMO-TN-KA-MH"
        states = {item["product_name"]: item["customs_status"] for item in shipment["consignments"]}
        assert states == {"Cotton shirts": "AT_HUB", "Stationery": "DELIVERED"}
        assert shipment["status"] == "PARTIALLY_DELIVERED"
        graph = client.get(f"/shipments/{shipment['id']}/graph").json()
        locations = [node for node in graph["nodes"] if node["type"] == "Location"]
        assert len(locations) == 3
        assert any("Bengaluru" in node["label"] for node in locations)
        assert len(client.get(f"/shipments/{shipment['id']}/timeline").json()["events"]) == 4


def test_domestic_creation_validation_and_delete():
    with TestClient(app) as client:
        source = demo(client)
        payload = {
            key: source[key]
            for key in (
                "shipment_reference",
                "exporter_country",
                "importer_country",
                "transport_mode",
                "planned_departure_at",
                "planned_arrival_at",
                "domestic",
                "consignments",
                "route_legs",
            )
        }
        payload["shipment_reference"] = "DOMESTIC-CREATE"
        created = client.post("/shipments", json=payload)
        assert created.status_code == 201, created.text
        shipment_id = created.json()["id"]
        assert client.post("/shipments", json=payload).status_code == 409
        payload["importer_country"] = "Germany"
        assert client.post("/shipments", json=payload).status_code == 422
        payload["importer_country"] = "India"
        payload["route_legs"][1]["domestic"]["origin"]["pincode"] = "600001"
        assert client.post("/shipments", json=payload).status_code == 422
        assert client.delete(f"/shipments/{shipment_id}").status_code == 204
        assert client.get(f"/shipments/{shipment_id}").status_code == 404
        assert shipment_id not in [item["id"] for item in client.get("/shipments").json()]


def test_late_event_and_later_arrival_preserve_completed_delivery():
    with TestClient(app) as client:
        shipment = demo(client)
        path = f"/shipments/{shipment['id']}/events"
        response = client.post(
            path,
            json={
                "event_type": "CREATED",
                "location_country": "India",
                "occurred_at": "2026-01-01T00:00:00Z",
                "metadata": {"location": shipment["domestic"]["origin"]},
            },
        )
        assert response.status_code == 201
        assert client.get(f"/shipments/{shipment['id']}").json()["status"] == "PARTIALLY_DELIVERED"
        response = client.post(
            path,
            json={
                "event_type": "ARRIVED_AT_HUB",
                "location_country": "India",
                "occurred_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "metadata": {"location": shipment["domestic"]["destination"]},
            },
        )
        assert response.status_code == 201
        updated = client.get(f"/shipments/{shipment['id']}").json()
        assert (
            next(item for item in updated["consignments"] if item["product_name"] == "Stationery")[
                "customs_status"
            ]
            == "DELIVERED"
        )


def test_wrong_delivery_location_and_foreign_event_rejected():
    with TestClient(app) as client:
        shipment = demo(client)
        path = f"/shipments/{shipment['id']}/events"
        payload = {
            "event_type": "DELIVERED",
            "location_country": "India",
            "consignment_id": next(
                item["id"]
                for item in shipment["consignments"]
                if item["product_name"] == "Cotton shirts"
            ),
            "occurred_at": datetime.now(UTC).isoformat(),
            "metadata": {"location": shipment["route_legs"][0]["domestic"]["destination"]},
        }
        assert client.post(path, json=payload).status_code == 422
        payload["metadata"]["location"] = shipment["domestic"]["destination"]
        payload["location_country"] = "UAE"
        assert client.post(path, json=payload).status_code == 422
        payload["location_country"] = "India"
        assert client.post(path, json=payload).status_code == 201
        assert client.get(f"/shipments/{shipment['id']}").json()["status"] == "DELIVERED"


def test_duplicate_route_sequence_is_rejected():
    with TestClient(app) as client:
        shipment = demo(client)
        assert (
            client.post(
                f"/shipments/{shipment['id']}/route-legs", json=shipment["route_legs"][0]
            ).status_code
            == 409
        )
