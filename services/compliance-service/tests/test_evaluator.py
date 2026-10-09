import os
import sys
from datetime import date
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["REDIS_ENABLED"] = "false"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.evaluator import effective_rules, evaluate_compliance, load_rules  # noqa: E402
from app.schemas import ComplianceStatus, UploadedDocumentMetadata  # noqa: E402

LITHIUM_ID = "consignment-lithium"
ELECTRONICS_ID = "consignment-electronics"


def domestic_shipment(value=50001, state="Maharashtra"):
    return {
        "id": "domestic",
        "transport_mode": "ROAD",
        "domestic": {
            "origin": {"state": "Tamil Nadu", "city": "Chennai", "pincode": "600001"},
            "destination": {"state": state, "city": "Pune", "pincode": "411001"},
            "registered_consignor": True,
            "ordinary_goods": True,
            "movement_reason": "SUPPLY",
        },
        "consignments": [
            {
                "id": "shirts",
                "product_name": "Cotton shirts",
                "domestic": {
                    "destination": {"state": state},
                    "consignment_value": value,
                },
            },
            {
                "id": "stationery",
                "product_name": "Stationery",
                "domestic": {
                    "destination": {"state": "Karnataka"},
                    "consignment_value": 20000,
                },
            },
        ],
    }


def domestic_documents():
    return [
        UploadedDocumentMetadata(
            document_id=f"invoice-{item}",
            document_type="tax_invoice",
            consignment_id=item,
            jurisdiction="India",
            metadata={"verification_status": "EXTRACTED"},
        )
        for item in ("shirts", "stationery")
    ]


def test_domestic_threshold_and_independent_consignment_outcomes():
    result = evaluate_compliance(domestic_shipment(), [], domestic_documents())
    by_id = {item.consignment_id: item for item in result.consignment_results}
    assert by_id["shirts"].status == ComplianceStatus.CONDITIONALLY_COMPLIANT
    assert by_id["shirts"].missing_documents == ["eway_bill"]
    assert by_id["stationery"].status == ComplianceStatus.COMPLIANT
    assert {rule.procedure_type for rule in result.applicable_rules} <= {"domestic", "interstate"}
    boundary = evaluate_compliance(domestic_shipment(50000), [], domestic_documents())
    assert boundary.status == ComplianceStatus.COMPLIANT


def test_domestic_documents_resolve_missing_eway_without_cross_consignment_leak():
    documents = domestic_documents() + [
        UploadedDocumentMetadata(
            document_id="eway",
            document_type="eway_bill",
            consignment_id="stationery",
            jurisdiction="India",
            metadata={"verification_status": "EXTRACTED"},
        )
    ]
    assert evaluate_compliance(domestic_shipment(), [], documents).missing_documents == [
        "eway_bill"
    ]
    documents[-1].consignment_id = "shirts"
    assert (
        evaluate_compliance(domestic_shipment(), [], documents).status == ComplianceStatus.COMPLIANT
    )


def test_intrastate_needs_state_confirmation_and_unsupported_movement_stays_unresolved():
    shipment = domestic_shipment(state="Tamil Nadu")
    assert (
        evaluate_compliance(shipment, [], domestic_documents()).status
        == ComplianceStatus.INSUFFICIENT_INFORMATION
    )
    result = evaluate_compliance(
        shipment, [], domestic_documents(), answers={"eway_bill_required:shirts": "yes"}
    )
    assert result.missing_documents == ["eway_bill"]
    result = evaluate_compliance(
        shipment, [], domestic_documents(), answers={"eway_bill_required:shirts": "no"}
    )
    assert result.status == ComplianceStatus.COMPLIANT
    shipment["domestic"]["ordinary_goods"] = False
    assert (
        evaluate_compliance(shipment, [], domestic_documents()).status
        == ComplianceStatus.INSUFFICIENT_INFORMATION
    )


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
        rule for rule in lithium_uae.applicable_rules if rule.rule_id == "TT-UAE-LITHIUM-SAFETY-001"
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
        rule for rule in lithium_uae.applicable_rules if rule.rule_id == "TT-UAE-LITHIUM-SAFETY-001"
    )
    assert battery_rule.status == ComplianceStatus.COMPLIANT
    assert battery_rule.supporting_document_ids == ["uploaded-safety-certificate"]
    assert battery_rule.shipment_event_id == "event-arrived-uae"


def test_rule_effective_dates_and_version_replacement():
    original = load_rules()[0]
    expired = original.model_copy(update={"effective_to": "2026-02-01"})
    future = original.model_copy(update={"effective_from": "2027-01-01"})
    replacement = original.model_copy(update={"version": "2026.2"})
    assert effective_rules([expired, future], date(2026, 9, 8)) == []
    assert effective_rules([original, replacement], date(2026, 9, 8)) == [replacement]


def test_empty_rule_set_does_not_fall_back_to_demo_rules():
    result = evaluate_compliance(sample_shipment(), sample_events(), [], rules=[])
    assert result.applicable_rules == []
    assert result.status == ComplianceStatus.INSUFFICIENT_INFORMATION


def test_answer_changes_transit_result_without_applying_import_rules():
    result = evaluate_compliance(
        sample_shipment(),
        sample_events(),
        complete_documents(),
        answers={f"sealed_onboard_uae:{LITHIUM_ID}": "no"},
    )
    transit = find_result(result, LITHIUM_ID, "UAE", "transit")
    assert transit.status == ComplianceStatus.CONDITIONALLY_COMPLIANT
    assert "handling procedure" in transit.recommended_action
    assert find_result(result, LITHIUM_ID, "UAE", "import") is None


def test_unknown_import_jurisdiction_cannot_be_marked_compliant():
    shipment = sample_shipment()
    shipment["consignments"][0]["destination_country"] = "Canada"
    result = evaluate_compliance(shipment, sample_events(), complete_documents())
    assert find_result(result, LITHIUM_ID, "Canada", "import").status == (
        ComplianceStatus.INSUFFICIENT_INFORMATION
    )


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
