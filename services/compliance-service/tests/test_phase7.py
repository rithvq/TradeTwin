# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

os.environ["AUTH_REQUIRED"] = "true"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["DOCUMENT_SERVICE_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"
os.environ["TRADETWIN_VIEWER_TOKEN"] = "viewer-token"
os.environ["TRADETWIN_OPERATOR_TOKEN"] = "operator-token"
os.environ["TRADETWIN_ADMIN_TOKEN"] = "admin-token"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from fastapi.testclient import TestClient

from tests.test_evaluator import sample_events, sample_shipment
from app.database import Base, engine
from app.main import app


def test_auth_me_returns_role_from_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer admin-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"actor_id": "demo-admin", "role": "admin"}


def test_rbac_blocks_viewer_from_admin_regulation_create() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/regulations",
            json={},
            headers={"Authorization": "Bearer viewer-token"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "HTTP_ERROR"
    assert response.headers["X-Trace-Id"]


def test_report_export_and_audit_log(monkeypatch) -> None:
    reset_database()
    monkeypatch.setattr(
        "app.main.get_shipment_context",
        lambda shipment_id: (sample_shipment(), sample_events()),
    )
    monkeypatch.setattr("app.main.get_uploaded_documents", lambda shipment_id: [])
    monkeypatch.setattr("app.main.get_evidence_records", lambda assessment_id: [])

    with TestClient(app) as client:
        html_response = client.get(
            "/reports/compliance/shipment-demo?format=html",
            headers={"Authorization": "Bearer operator-token"},
        )
        pdf_response = client.get(
            "/reports/compliance/shipment-demo?format=pdf",
            headers={"Authorization": "Bearer operator-token"},
        )
        audit_response = client.get(
            "/audit-logs?shipment_id=shipment-demo",
            headers={"Authorization": "Bearer admin-token"},
        )

    assert html_response.status_code == 200
    assert "TradeTwin Compliance Report" in html_response.text
    assert "evaluation only" in html_response.text
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF")
    assert audit_response.status_code == 200
    actions = [item["action"] for item in audit_response.json()]
    assert "COMPLIANCE_REPORT_EXPORTED" in actions
    assert "COMPLIANCE_ASSESSMENT_CREATED" in actions


def test_demo_scenarios_endpoint_lists_walkthrough() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/scenarios")

    assert response.status_code == 200
    scenario = response.json()[0]
    assert scenario["shipment_reference"] == "TT-DEMO-IND-UAE-DEU"
    assert "Export evidence-grounded report" in scenario["walkthrough_steps"]


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
