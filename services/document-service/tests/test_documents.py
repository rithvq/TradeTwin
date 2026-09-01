import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["MINIO_ENABLED"] = "false"
os.environ["LOCAL_OBJECT_STORAGE_PATH"] = str(
    Path(tempfile.gettempdir()) / "tradetwin-document-service-tests"
)

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app  # noqa: E402


def test_upload_and_extract_safety_certificate_metadata() -> None:
    content = "\n".join(
        [
            "Document Number: SAFE-IND-UAE-001",
            "Document Date: 2026-09-01",
            "Product Name: Lithium batteries",
            "Quantity: 120",
            "Declared Value: USD 18000.00",
            "Country of Origin: India",
        ]
    ).encode()

    with TestClient(app) as client:
        upload_response = client.post(
            "/shipments/shipment-demo/documents",
            data={
                "document_type": "safety_certificate",
                "consignment_id": "consignment-lithium",
                "shipment_event_id": "event-arrived-uae",
                "jurisdiction": "UAE",
            },
            files={"file": ("battery-safety.txt", content, "text/plain")},
        )
        assert upload_response.status_code == 201
        document_id = upload_response.json()["id"]

        extract_response = client.post(f"/documents/{document_id}/extract")
        assert extract_response.status_code == 200

        payload = extract_response.json()
        assert payload["verification_status"] == "EXTRACTED"
        assert payload["document_number"] == "SAFE-IND-UAE-001"
        assert payload["document_date"] == "2026-09-01"
        assert payload["extracted_fields"]["product_name"] == "Lithium batteries"
        assert payload["extracted_fields"]["quantity"] == "120"
        assert payload["extracted_fields"]["declared_value"] == "USD 18000.00"
        assert payload["extracted_fields"]["country_of_origin"] == "India"


def test_assessment_evidence_records_link_rule_document_and_event() -> None:
    with TestClient(app) as client:
        upload_response = client.post(
            "/shipments/shipment-demo/documents",
            data={
                "document_type": "safety_certificate",
                "consignment_id": "consignment-lithium",
                "shipment_event_id": "event-arrived-uae",
                "jurisdiction": "UAE",
            },
            files={
                "file": (
                    "battery-safety.txt",
                    b"Product Name: Lithium batteries",
                    "text/plain",
                )
            },
        )
        document_id = upload_response.json()["id"]

        evidence_response = client.post(
            "/assessments/assessment-1/evidence",
            json={
                "records": [
                    {
                        "shipment_id": "shipment-demo",
                        "consignment_id": "consignment-lithium",
                        "rule_id": "TT-UAE-LITHIUM-SAFETY-001",
                        "rule_title": "UAE demo lithium battery safety certificate requirement",
                        "regulation_version": "2026.1",
                        "regulation_source_url": (
                            "https://example.com/rules/uae/lithium-battery-safety"
                        ),
                        "document_id": document_id,
                        "shipment_event_id": "event-arrived-uae",
                        "jurisdiction": "UAE",
                        "procedure_type": "transit",
                        "evidence_type": "DOCUMENT_SUPPORTS_RULE",
                        "explanation": "Safety certificate supports UAE lithium transit rule.",
                    }
                ]
            },
        )
        assert evidence_response.status_code == 201

        get_response = client.get("/assessments/assessment-1/evidence")
        assert get_response.status_code == 200
        records = get_response.json()
        assert len(records) == 1
        assert records[0]["assessment_id"] == "assessment-1"
        assert records[0]["rule_id"] == "TT-UAE-LITHIUM-SAFETY-001"
        assert records[0]["document_id"] == document_id
        assert records[0]["shipment_event_id"] == "event-arrived-uae"
        assert records[0]["document"]["document_type"] == "safety_certificate"
