# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["DOCUMENT_SERVICE_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from tests.test_evaluator import (
    LITHIUM_ID,
    documents_without_battery_certificate,
    sample_events,
    sample_shipment,
)
from app.document_client import build_evidence_records
from app.evaluator import evaluate_compliance
from app.schemas import UploadedDocumentMetadata


def test_evidence_records_link_assessment_rule_document_version_and_event() -> None:
    documents = documents_without_battery_certificate()
    documents.append(
        UploadedDocumentMetadata(
            document_id="doc-safety",
            document_type="safety_certificate",
            filename="battery-safety.pdf",
            consignment_id=LITHIUM_ID,
            shipment_event_id="event-arrived-uae",
            jurisdiction="UAE",
            metadata={"verification_status": "EXTRACTED"},
        )
    )

    result = evaluate_compliance(sample_shipment(), sample_events(), documents)
    evidence_records = build_evidence_records(result, documents)

    safety_record = next(
        record
        for record in evidence_records
        if record["rule_id"] == "TT-UAE-LITHIUM-SAFETY-001"
        and record["document_id"] == "doc-safety"
    )
    assert safety_record["regulation_version"] == "2026.1"
    assert safety_record["shipment_event_id"] == "event-arrived-uae"
    assert safety_record["evidence_type"] == "DOCUMENT_SUPPORTS_RULE"
