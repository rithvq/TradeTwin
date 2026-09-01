import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["REDIS_ENABLED"] = "false"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.evaluator import evaluate_compliance  # noqa: E402
from app.schemas import ComplianceStatus, UploadedDocumentMetadata  # noqa: E402

LITHIUM_ID = "consignment-lithium"
ELECTRONICS_ID = "consignment-electronics"


def test_transit_rules_differ_from_import_rules() -> None:
    assessment = evaluate_compliance(sample_shipment(), sample_events(), complete_documents())

    lithium_uae = find_result(assessment, LITHIUM_ID, "UAE", "transit")
    electronics_uae = find_result(assessment, ELECTRONICS_ID, "UAE", "import")

    assert lithium_uae is not None
    assert electronics_uae is not None
    assert all(rule.procedure_type != "import" for rule in lithium_uae.applicable_rules)
    assert all(rule.procedure_type != "transit" for rule in electronics_uae.applicable_rules)
    assert lithium_uae.status == ComplianceStatus.COMPLIANT
    assert electronics_uae.status == ComplianceStatus.COMPLIANT


def test_two_consignments_can_have_different_compliance_outcomes() -> None:
    assessment = evaluate_compliance(
        sample_shipment(),
        sample_events(),
        documents_without_battery_certificate(),
    )

    lithium_uae = find_result(assessment, LITHIUM_ID, "UAE", "transit")
    electronics_uae = find_result(assessment, ELECTRONICS_ID, "UAE", "import")

    assert lithium_uae is not None
    assert electronics_uae is not None
    assert lithium_uae.status == ComplianceStatus.CONDITIONALLY_COMPLIANT
    assert electronics_uae.status == ComplianceStatus.COMPLIANT


def test_missing_battery_certificate_creates_conditional_compliance() -> None:
    assessment = evaluate_compliance(
        sample_shipment(),
        sample_events(),
        documents_without_battery_certificate(),
    )

    lithium_uae = find_result(assessment, LITHIUM_ID, "UAE", "transit")
    assert lithium_uae is not None

    battery_rule = next(
        rule
        for rule in lithium_uae.applicable_rules
        if rule.rule_id == "TT-UAE-LITHIUM-SAFETY-001"
    )
    assert battery_rule.status == ComplianceStatus.CONDITIONALLY_COMPLIANT
    assert battery_rule.missing_documents == ["lithium_battery_safety_certificate"]


def test_extracted_safety_certificate_satisfies_lithium_battery_rule() -> None:
    documents = documents_without_battery_certificate()
    documents.append(
        UploadedDocumentMetadata(
            document_id="uploaded-safety-certificate",
            document_type="safety_certificate",
            filename="battery-safety.pdf",
            consignment_id=LITHIUM_ID,
            shipment_event_id="event-arrived-uae",
            jurisdiction="UAE",
            metadata={"verification_status": "EXTRACTED"},
        )
    )

    assessment = evaluate_compliance(sample_shipment(), sample_events(), documents)
    lithium_uae = find_result(assessment, LITHIUM_ID, "UAE", "transit")
    assert lithium_uae is not None

    battery_rule = next(
        rule
        for rule in lithium_uae.applicable_rules
        if rule.rule_id == "TT-UAE-LITHIUM-SAFETY-001"
    )
    assert battery_rule.status == ComplianceStatus.COMPLIANT
    assert battery_rule.supporting_document_ids == ["uploaded-safety-certificate"]
    assert battery_rule.shipment_event_id == "event-arrived-uae"


def find_result(assessment, consignment_id: str, jurisdiction: str, procedure_type: str):
    return next(
        (
            result
            for result in assessment.consignment_results
            if result.consignment_id == consignment_id
            and result.jurisdiction == jurisdiction
            and result.procedure_type == procedure_type
        ),
        None,
    )


def complete_documents() -> list[UploadedDocumentMetadata]:
    documents = documents_without_battery_certificate()
    documents.append(document("lithium_battery_safety_certificate"))
    return documents


def documents_without_battery_certificate() -> list[UploadedDocumentMetadata]:
    return [
        document("commercial_invoice"),
        document("packing_list"),
        document("export_declaration"),
        document("import_declaration"),
        document("certificate_of_origin"),
        document("transit_declaration"),
    ]


def document(document_type: str) -> UploadedDocumentMetadata:
    return UploadedDocumentMetadata(
        document_id=f"doc-{document_type}",
        document_type=document_type,
        filename=f"{document_type}.pdf",
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
                "id": LITHIUM_ID,
                "shipment_id": "shipment-demo",
                "product_name": "Lithium batteries",
                "product_description": "Rechargeable lithium battery packs.",
                "quantity": 120,
                "declared_value": "18000.00",
                "currency": "USD",
                "country_of_origin": "India",
                "destination_country": "Germany",
                "proposed_hs_code": None,
                "customs_status": "UAE_TRANSIT",
            },
            {
                "id": ELECTRONICS_ID,
                "shipment_id": "shipment-demo",
                "product_name": "Consumer electronics",
                "product_description": "Packaged consumer electronics.",
                "quantity": 240,
                "declared_value": "32000.00",
                "currency": "USD",
                "country_of_origin": "India",
                "destination_country": "UAE",
                "proposed_hs_code": None,
                "customs_status": "UAE_IMPORT",
            },
        ],
        "route_legs": [
            {
                "id": "leg-1",
                "shipment_id": "shipment-demo",
                "sequence_number": 1,
                "origin_country": "India",
                "destination_country": "UAE",
                "transport_mode": "SEA",
                "carrier_name": "TradeTwin Demo Line",
            },
            {
                "id": "leg-2",
                "shipment_id": "shipment-demo",
                "sequence_number": 2,
                "origin_country": "UAE",
                "destination_country": "Germany",
                "transport_mode": "SEA",
                "carrier_name": "TradeTwin Demo Line",
            },
        ],
    }


def sample_events() -> list[dict]:
    return [
        {
            "id": "event-created",
            "shipment_id": "shipment-demo",
            "consignment_id": None,
            "event_type": "CREATED",
            "location_country": "India",
            "occurred_at": "2026-08-29T00:00:00Z",
            "metadata": {"source": "test"},
        },
        {
            "id": "event-loaded-lithium",
            "shipment_id": "shipment-demo",
            "consignment_id": LITHIUM_ID,
            "event_type": "LOADED",
            "location_country": "India",
            "occurred_at": "2026-08-29T02:00:00Z",
            "metadata": {"source": "test"},
        },
        {
            "id": "event-loaded-electronics",
            "shipment_id": "shipment-demo",
            "consignment_id": ELECTRONICS_ID,
            "event_type": "LOADED",
            "location_country": "India",
            "occurred_at": "2026-08-29T02:05:00Z",
            "metadata": {"source": "test"},
        },
        {
            "id": "event-arrived-uae",
            "shipment_id": "shipment-demo",
            "consignment_id": None,
            "event_type": "ARRIVED_AT_TRANSIT_PORT",
            "location_country": "UAE",
            "occurred_at": "2026-09-05T00:00:00Z",
            "metadata": {"source": "test"},
        },
        {
            "id": "event-unloaded-electronics",
            "shipment_id": "shipment-demo",
            "consignment_id": ELECTRONICS_ID,
            "event_type": "UNLOADED",
            "location_country": "UAE",
            "occurred_at": "2026-09-05T03:00:00Z",
            "metadata": {"source": "test"},
        },
    ]
