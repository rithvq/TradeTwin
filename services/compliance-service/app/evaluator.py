import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.schemas import (
    ApplicableRuleResult,
    ComplianceAssessmentResult,
    ComplianceRule,
    ComplianceStatus,
    ConsignmentComplianceResult,
    UploadedDocumentMetadata,
)

RULES_DIR = Path(__file__).resolve().parent / "rules"

STATUS_SEVERITY = {
    ComplianceStatus.COMPLIANT: 0,
    ComplianceStatus.INSUFFICIENT_INFORMATION: 1,
    ComplianceStatus.CONDITIONALLY_COMPLIANT: 2,
    ComplianceStatus.NON_COMPLIANT: 3,
}

DOCUMENT_TYPE_ALIASES = {
    "lithium_battery_safety_certificate": {
        "lithium_battery_safety_certificate",
        "safety_certificate",
    },
}


def load_rules() -> list[ComplianceRule]:
    rules: list[ComplianceRule] = []
    for path in sorted(RULES_DIR.glob("*.json")):
        raw_rules = json.loads(path.read_text(encoding="utf-8"))
        rules.extend(ComplianceRule.model_validate(rule) for rule in raw_rules)
    return rules


def evaluate_compliance(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    uploaded_documents: list[UploadedDocumentMetadata],
    rules: list[ComplianceRule] | None = None,
) -> ComplianceAssessmentResult:
    active_rules = rules or load_rules()
    consignments = shipment.get("consignments", [])
    group_results: dict[tuple[str, str, str], list[ApplicableRuleResult]] = defaultdict(list)

    for consignment in consignments:
        for rule in active_rules:
            if not rule_applies(rule, shipment, consignment, events):
                continue
            event_id = find_matching_event_id(rule, consignment, events)
            result = evaluate_rule(rule, consignment, uploaded_documents, event_id)
            key = (consignment["id"], rule.jurisdiction, rule.procedure_type)
            group_results[key].append(result)

    consignment_results = [
        build_consignment_result(consignments, key, rule_results)
        for key, rule_results in group_results.items()
    ]
    consignment_results.sort(
        key=lambda item: (item.product_name, item.jurisdiction, item.procedure_type)
    )

    applicable_rules = [
        rule_result
        for consignment_result in consignment_results
        for rule_result in consignment_result.applicable_rules
    ]
    missing_documents = unique_ordered(
        missing
        for consignment_result in consignment_results
        for missing in consignment_result.missing_documents
    )
    violations = unique_ordered(
        violation
        for consignment_result in consignment_results
        for violation in consignment_result.violations
    )
    recommended_actions = unique_ordered(
        consignment_result.recommended_action
        for consignment_result in consignment_results
        if consignment_result.recommended_action != "No action required."
    )

    status = aggregate_status([result.status for result in consignment_results])
    return ComplianceAssessmentResult(
        shipment_id=shipment["id"],
        status=status,
        applicable_rules=applicable_rules,
        missing_documents=missing_documents,
        violations=violations,
        recommended_action="; ".join(recommended_actions) or "No action required.",
        consignment_results=consignment_results,
    )


def evaluate_rule(
    rule: ComplianceRule,
    consignment: dict[str, Any],
    uploaded_documents: list[UploadedDocumentMetadata],
    shipment_event_id: str | None = None,
) -> ApplicableRuleResult:
    if rule.conditions.get("fail_when_matched") is True:
        return ApplicableRuleResult(
            rule_id=rule.rule_id,
            title=rule.title,
            jurisdiction=rule.jurisdiction,
            procedure_type=rule.procedure_type,
            version=rule.version,
            effective_from=rule.effective_from,
            effective_to=rule.effective_to,
            source_url=rule.source_url,
            required_documents=rule.required_documents,
            status=rule.outcome_if_failed.status,
            missing_documents=[],
            supporting_document_ids=[],
            shipment_event_id=shipment_event_id,
            violation=rule.outcome_if_failed.violation,
            recommended_action=rule.outcome_if_failed.recommended_action,
        )

    supporting_documents_by_type = {
        document_type: matching_documents(document_type, rule, consignment, uploaded_documents)
        for document_type in rule.required_documents
    }
    missing_documents = [
        document_type
        for document_type in rule.required_documents
        if not supporting_documents_by_type[document_type]
    ]
    supporting_document_ids = unique_ordered(
        document.document_id
        for documents in supporting_documents_by_type.values()
        for document in documents
    )
    status = ComplianceStatus.COMPLIANT
    violation = None
    recommended_action = None
    if missing_documents:
        status = rule.outcome_if_failed.status
        violation = rule.outcome_if_failed.violation
        recommended_action = rule.outcome_if_failed.recommended_action

    return ApplicableRuleResult(
        rule_id=rule.rule_id,
        title=rule.title,
        jurisdiction=rule.jurisdiction,
        procedure_type=rule.procedure_type,
        version=rule.version,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        source_url=rule.source_url,
        required_documents=rule.required_documents,
        status=status,
        missing_documents=missing_documents,
        supporting_document_ids=supporting_document_ids,
        shipment_event_id=shipment_event_id,
        violation=violation,
        recommended_action=recommended_action,
    )


def build_consignment_result(
    consignments: list[dict[str, Any]],
    key: tuple[str, str, str],
    rule_results: list[ApplicableRuleResult],
) -> ConsignmentComplianceResult:
    consignment_id, jurisdiction, procedure_type = key
    consignment = next(item for item in consignments if item["id"] == consignment_id)
    missing_documents = unique_ordered(
        missing for result in rule_results for missing in result.missing_documents
    )
    violations = unique_ordered(
        result.violation for result in rule_results if result.violation is not None
    )
    actions = unique_ordered(
        result.recommended_action
        for result in rule_results
        if result.recommended_action is not None
    )

    return ConsignmentComplianceResult(
        consignment_id=consignment_id,
        product_name=consignment["product_name"],
        jurisdiction=jurisdiction,
        procedure_type=procedure_type,
        status=aggregate_status([result.status for result in rule_results]),
        applicable_rules=rule_results,
        missing_documents=missing_documents,
        violations=violations,
        recommended_action="; ".join(actions) or "No action required.",
    )


def rule_applies(
    rule: ComplianceRule,
    shipment: dict[str, Any],
    consignment: dict[str, Any],
    events: list[dict[str, Any]],
) -> bool:
    conditions = rule.conditions

    exporter_country = conditions.get("shipment_exporter_country")
    if exporter_country and shipment.get("exporter_country") != exporter_country:
        return False

    if conditions.get("route_contains_jurisdiction") is True and not route_contains(
        shipment, rule.jurisdiction
    ):
        return False

    if conditions.get("consignment_destination_is_jurisdiction") is True:
        if consignment.get("destination_country") != rule.jurisdiction:
            return False

    if conditions.get("consignment_destination_is_not_jurisdiction") is True:
        if consignment.get("destination_country") == rule.jurisdiction:
            return False

    if conditions.get("country_of_origin_is_not_jurisdiction") is True:
        if consignment.get("country_of_origin") == rule.jurisdiction:
            return False

    keywords = conditions.get("product_keywords")
    if keywords and not product_contains_keywords(consignment, keywords):
        return False

    if "event_types" in conditions or "event_location_country" in conditions:
        if find_matching_event_id(rule, consignment, events) is None:
            return False

    return True


def route_contains(shipment: dict[str, Any], jurisdiction: str) -> bool:
    if shipment.get("exporter_country") == jurisdiction:
        return True
    if shipment.get("importer_country") == jurisdiction:
        return True
    for leg in shipment.get("route_legs", []):
        if (
            leg.get("origin_country") == jurisdiction
            or leg.get("destination_country") == jurisdiction
        ):
            return True
    return False


def find_matching_event_id(
    rule: ComplianceRule,
    consignment: dict[str, Any],
    events: list[dict[str, Any]],
) -> str | None:
    event_types = set(rule.conditions.get("event_types", []))
    event_location = rule.conditions.get("event_location_country")

    for event in events:
        if event_types and event.get("event_type") not in event_types:
            continue
        if event_location and event.get("location_country") != event_location:
            continue
        if event.get("consignment_id") not in (None, consignment["id"]):
            continue
        return event.get("id")
    return None


def product_contains_keywords(consignment: dict[str, Any], keywords: list[str]) -> bool:
    haystack = " ".join(
        [
            str(consignment.get("product_name", "")),
            str(consignment.get("product_description", "")),
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def matching_documents(
    document_type: str,
    rule: ComplianceRule,
    consignment: dict[str, Any],
    uploaded_documents: list[UploadedDocumentMetadata],
) -> list[UploadedDocumentMetadata]:
    matches = []
    for document in uploaded_documents:
        if not document_type_matches(document_type, document.document_type):
            continue
        if document.consignment_id and document.consignment_id != consignment["id"]:
            continue
        if document.jurisdiction and document.jurisdiction != rule.jurisdiction:
            continue
        if not document_is_usable(document):
            continue
        matches.append(document)
    return matches


def document_type_matches(required_type: str, actual_type: str) -> bool:
    accepted_types = DOCUMENT_TYPE_ALIASES.get(required_type, {required_type})
    return actual_type in accepted_types


def document_is_usable(document: UploadedDocumentMetadata) -> bool:
    verification_status = document.metadata.get("verification_status")
    if verification_status is None:
        return True
    return str(verification_status).upper() in {"EXTRACTED", "VERIFIED"}


def aggregate_status(statuses: list[ComplianceStatus]) -> ComplianceStatus:
    if not statuses:
        return ComplianceStatus.INSUFFICIENT_INFORMATION
    return max(statuses, key=lambda status: STATUS_SEVERITY[status])


def unique_ordered(values) -> list[str]:
    seen = set()
    unique_values = []
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
