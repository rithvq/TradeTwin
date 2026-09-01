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

from tests.test_evaluator import LITHIUM_ID, sample_events, sample_shipment
from app.consistency import check_consistency, highest_value_question
from app.schemas import UploadedDocumentMetadata


def test_origin_conflict_across_documents() -> None:
    result = check_consistency(
        sample_shipment(),
        sample_events(),
        [
            document("doc-invoice", "commercial_invoice", LITHIUM_ID, country_of_origin="India"),
            document(
                "doc-origin",
                "certificate_of_origin",
                LITHIUM_ID,
                country_of_origin="China",
            ),
        ],
    )

    assert any(conflict.conflict_type == "origin_conflict" for conflict in result.conflicts)
    conflict = next(
        conflict for conflict in result.conflicts if conflict.conflict_type == "origin_conflict"
    )
    assert conflict.severity == "HIGH"
    assert set(conflict.document_ids) == {"doc-invoice", "doc-origin"}


def test_quantity_conflict_across_documents() -> None:
    result = check_consistency(
        sample_shipment(),
        sample_events(),
        [
            document("doc-invoice", "commercial_invoice", LITHIUM_ID, quantity="120"),
            document("doc-packing", "packing_list", LITHIUM_ID, quantity="118"),
        ],
    )

    assert any(conflict.conflict_type == "quantity_mismatch" for conflict in result.conflicts)
    conflict = next(
        conflict
        for conflict in result.conflicts
        if conflict.conflict_type == "quantity_mismatch"
    )
    assert conflict.severity == "HIGH"
    assert "doc-invoice=120" in conflict.details
    assert "doc-packing=118" in conflict.details


def test_transit_status_question_is_highest_value_question() -> None:
    question = highest_value_question(
        sample_shipment(),
        sample_events(),
        [],
        answers={},
    )

    assert question is not None
    assert (
        question.question
        == "Will the lithium batteries consignment remain sealed onboard in UAE?"
    )
    assert question.impact_score == 100
    assert "TT-UAE-TRANSIT-001" in question.affects_rules


def test_answered_transit_status_question_is_not_repeated() -> None:
    question = highest_value_question(
        sample_shipment(),
        sample_events(),
        [],
        answers={f"sealed_onboard_uae:{LITHIUM_ID}": "yes"},
    )

    assert question is not None
    assert question.attribute_key != f"sealed_onboard_uae:{LITHIUM_ID}"


def document(
    document_id: str,
    document_type: str,
    consignment_id: str,
    **fields,
) -> UploadedDocumentMetadata:
    return UploadedDocumentMetadata(
        document_id=document_id,
        document_type=document_type,
        filename=f"{document_type}.pdf",
        consignment_id=consignment_id,
        metadata={
            "verification_status": "EXTRACTED",
            "extracted_fields": fields,
        },
    )
