from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domestic import domestic_questions
from app.evaluator import evaluate_compliance
from app.schemas import (
    ComplianceRule,
    ConflictSeverity,
    ConsistencyCheckRead,
    ConsistencyConflict,
    InformationGainQuestionRead,
    UploadedDocumentMetadata,
)

UAE_LITHIUM_RULE_ID = "TT-UAE-LITHIUM-SAFETY-001"
UAE_TRANSIT_RULE_ID = "TT-UAE-TRANSIT-001"


def check_consistency(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    documents: list[UploadedDocumentMetadata],
    answers: dict[str, str] | None = None,
) -> ConsistencyCheckRead:
    answers = answers or {}
    conflicts = [
        *(domestic_location_conflicts(shipment, documents) if shipment.get("domestic") else []),
        *origin_conflicts(shipment, documents),
        *hs_code_conflicts(shipment, documents),
        *invoice_value_conflicts(shipment, documents),
        *quantity_conflicts(shipment, documents),
        *(
            missing_certificate_conflicts(shipment, documents)
            if not shipment.get("domestic")
            else []
        ),
        *(
            procedure_conflicts(shipment, events, documents, answers)
            if not shipment.get("domestic")
            else []
        ),
        *(route_conflicts(shipment, events) if not shipment.get("domestic") else []),
    ]
    conflicts.sort(key=lambda conflict: (severity_rank(conflict.severity), conflict.title))
    return ConsistencyCheckRead(
        shipment_id=shipment["id"],
        checked_at=datetime.now(UTC),
        conflicts=conflicts,
    )


def highest_value_question(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    documents: list[UploadedDocumentMetadata],
    answers: dict[str, str] | None = None,
    rules: list[ComplianceRule] | None = None,
) -> InformationGainQuestionRead | None:
    answers = answers or {}
    candidates = build_question_candidates(shipment, events, documents, rules)
    unanswered = [question for question in candidates if question.attribute_key not in answers]
    if not unanswered:
        return None
    unanswered.sort(key=lambda question: (-question.impact_score, question.question))
    return unanswered[0]


def question_catalog(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    documents: list[UploadedDocumentMetadata],
    rules: list[ComplianceRule] | None = None,
) -> list[InformationGainQuestionRead]:
    return build_question_candidates(shipment, events, documents, rules)


def build_question_candidates(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    documents: list[UploadedDocumentMetadata],
    rules: list[ComplianceRule] | None = None,
) -> list[InformationGainQuestionRead]:
    if shipment.get("domestic"):
        return domestic_questions(shipment)
    candidates: list[InformationGainQuestionRead] = []

    for consignment in shipment.get("consignments", []):
        if (
            is_lithium(consignment)
            and consignment.get("destination_country") != "UAE"
            and route_contains(shipment, "UAE")
            and has_event(events, "ARRIVED_AT_TRANSIT_PORT", "UAE", consignment_id=None)
        ):
            candidates.append(
                InformationGainQuestionRead(
                    question_id=f"q-sealed-onboard-uae-{consignment['id']}",
                    shipment_id=shipment["id"],
                    consignment_id=consignment["id"],
                    attribute_key=f"sealed_onboard_uae:{consignment['id']}",
                    question=(
                        f"Will the {consignment['product_name'].lower()} consignment "
                        "remain sealed onboard in UAE?"
                    ),
                    impact_score=100,
                    affects_rules=[
                        UAE_TRANSIT_RULE_ID,
                        UAE_LITHIUM_RULE_ID,
                        "TT-UAE-TRANSIT-HANDLING-001",
                    ],
                    why_this_matters=(
                        "This confirms whether UAE transit rules remain the right "
                        "procedure instead of triggering an import-style treatment."
                    ),
                    answer_options=["Yes", "No", "Unknown"],
                )
            )

        if is_lithium(consignment) and not has_certificate_for(consignment, documents):
            candidates.append(
                InformationGainQuestionRead(
                    question_id=f"q-safety-certificate-{consignment['id']}",
                    shipment_id=shipment["id"],
                    consignment_id=consignment["id"],
                    attribute_key=f"safety_certificate_available:{consignment['id']}",
                    question=(
                        f"Is a lithium battery safety certificate available for "
                        f"{consignment['product_name'].lower()}?"
                    ),
                    impact_score=90,
                    affects_rules=[UAE_LITHIUM_RULE_ID],
                    why_this_matters=(
                        "The UAE lithium transit rule cannot fully clear without "
                        "evidence of the safety certificate."
                    ),
                    answer_options=["Yes", "No", "Unknown"],
                )
            )

    assessment = evaluate_compliance(shipment, events, documents, rules)
    seen_attributes = {candidate.attribute_key for candidate in candidates}
    for consignment_result in assessment.consignment_results:
        for missing_document in consignment_result.missing_documents:
            attribute_key = (
                f"document_available:{consignment_result.consignment_id}:{missing_document}"
            )
            if attribute_key in seen_attributes:
                continue
            seen_attributes.add(attribute_key)
            candidates.append(
                InformationGainQuestionRead(
                    question_id=stable_question_id(attribute_key),
                    shipment_id=shipment["id"],
                    consignment_id=consignment_result.consignment_id,
                    attribute_key=attribute_key,
                    question=(
                        f"Is {display_label(missing_document)} available for "
                        f"{consignment_result.product_name}?"
                    ),
                    impact_score=impact_for_status(consignment_result.status),
                    affects_rules=[
                        rule.rule_id
                        for rule in consignment_result.applicable_rules
                        if missing_document in rule.missing_documents
                    ],
                    why_this_matters=(
                        "This document is currently blocking one or more deterministic "
                        "compliance decisions."
                    ),
                    answer_options=["Yes", "No", "Unknown"],
                )
            )

    return candidates


def origin_conflicts(
    shipment: dict[str, Any],
    documents: list[UploadedDocumentMetadata],
) -> list[ConsistencyConflict]:
    conflicts: list[ConsistencyConflict] = []
    for group_key, group_docs in grouped_documents(documents).items():
        origin_values = field_values(group_docs, "country_of_origin")
        if len(origin_values) > 1:
            conflicts.append(
                conflict(
                    shipment,
                    group_key,
                    group_docs,
                    "origin_conflict",
                    ConflictSeverity.HIGH,
                    "Conflicting country of origin",
                    f"Documents report different origins: {', '.join(origin_values)}.",
                    "Origin drives import requirements, certificates, and restricted-goods review.",
                )
            )

        consignment = consignment_for_group(shipment, group_key)
        if consignment and origin_values:
            recorded_origin = normalize_text(consignment.get("country_of_origin"))
            doc_origins = {normalize_text(value) for value in origin_values}
            if recorded_origin and recorded_origin not in doc_origins:
                conflicts.append(
                    conflict(
                        shipment,
                        group_key,
                        group_docs,
                        "origin_conflict",
                        ConflictSeverity.HIGH,
                        "Document origin conflicts with consignment",
                        (
                            f"Consignment origin is {consignment['country_of_origin']}, "
                            f"but documents report {', '.join(origin_values)}."
                        ),
                        "Origin mismatch can change certificate and import review outcomes.",
                    )
                )
    return conflicts


def hs_code_conflicts(
    shipment: dict[str, Any],
    documents: list[UploadedDocumentMetadata],
) -> list[ConsistencyConflict]:
    conflicts: list[ConsistencyConflict] = []
    for group_key, group_docs in grouped_documents(documents).items():
        hs_values = field_values(group_docs, "hs_code", "proposed_hs_code")
        if len(hs_values) > 1:
            conflicts.append(
                conflict(
                    shipment,
                    group_key,
                    group_docs,
                    "hs_code_conflict",
                    ConflictSeverity.HIGH,
                    "Inconsistent HS code",
                    f"Documents report different HS codes: {', '.join(hs_values)}.",
                    "HS code drives the rule path, controls checks, and duty assumptions.",
                )
            )
        consignment = consignment_for_group(shipment, group_key)
        proposed_hs_code = normalize_text(
            consignment.get("proposed_hs_code") if consignment else None
        )
        if proposed_hs_code and hs_values:
            if proposed_hs_code not in {normalize_text(value) for value in hs_values}:
                conflicts.append(
                    conflict(
                        shipment,
                        group_key,
                        group_docs,
                        "hs_code_conflict",
                        ConflictSeverity.HIGH,
                        "Document HS code conflicts with consignment",
                        (
                            f"Consignment HS code is {consignment['proposed_hs_code']}, "
                            f"but documents report {', '.join(hs_values)}."
                        ),
                        "HS code mismatch can send the shipment through the wrong rules.",
                    )
                )
    return conflicts


def invoice_value_conflicts(
    shipment: dict[str, Any],
    documents: list[UploadedDocumentMetadata],
) -> list[ConsistencyConflict]:
    conflicts: list[ConsistencyConflict] = []
    for group_key, group_docs in grouped_documents(documents).items():
        numeric_values = numeric_field_values(group_docs, "declared_value", "invoice_value")
        if len(set(numeric_values.values())) > 1:
            conflicts.append(
                conflict(
                    shipment,
                    group_key,
                    group_docs,
                    "invoice_value_mismatch",
                    ConflictSeverity.HIGH,
                    "Invoice value mismatch",
                    f"Documents report different values: {format_numeric_map(numeric_values)}.",
                    "Declared value affects import review, valuation checks, and duty assumptions.",
                )
            )

        consignment = consignment_for_group(shipment, group_key)
        if consignment and numeric_values:
            recorded_value = to_decimal(consignment.get("declared_value"))
            if recorded_value is not None and recorded_value not in set(numeric_values.values()):
                conflicts.append(
                    conflict(
                        shipment,
                        group_key,
                        group_docs,
                        "invoice_value_mismatch",
                        ConflictSeverity.HIGH,
                        "Document value conflicts with consignment",
                        (
                            f"Consignment declared value is {recorded_value}, "
                            f"but documents report {format_numeric_map(numeric_values)}."
                        ),
                        "Value mismatch leaves valuation-dependent compliance unresolved.",
                    )
                )
    return conflicts


def quantity_conflicts(
    shipment: dict[str, Any],
    documents: list[UploadedDocumentMetadata],
) -> list[ConsistencyConflict]:
    conflicts: list[ConsistencyConflict] = []
    for group_key, group_docs in grouped_documents(documents).items():
        numeric_values = numeric_field_values(group_docs, "quantity")
        if len(set(numeric_values.values())) > 1:
            conflicts.append(
                conflict(
                    shipment,
                    group_key,
                    group_docs,
                    "quantity_mismatch",
                    ConflictSeverity.HIGH,
                    "Quantity mismatch",
                    f"Documents report different quantities: {format_numeric_map(numeric_values)}.",
                    "Quantity affects packing, invoice validation, and import declaration review.",
                )
            )

        consignment = consignment_for_group(shipment, group_key)
        if consignment and numeric_values:
            recorded_quantity = to_decimal(consignment.get("quantity"))
            if recorded_quantity is not None and recorded_quantity not in set(
                numeric_values.values()
            ):
                conflicts.append(
                    conflict(
                        shipment,
                        group_key,
                        group_docs,
                        "quantity_mismatch",
                        ConflictSeverity.HIGH,
                        "Document quantity conflicts with consignment",
                        (
                            f"Consignment quantity is {recorded_quantity}, "
                            f"but documents report {format_numeric_map(numeric_values)}."
                        ),
                        "Quantity mismatch can invalidate invoice and packing evidence.",
                    )
                )
    return conflicts


def missing_certificate_conflicts(
    shipment: dict[str, Any],
    documents: list[UploadedDocumentMetadata],
) -> list[ConsistencyConflict]:
    conflicts = []
    for consignment in shipment.get("consignments", []):
        if is_lithium(consignment) and not has_certificate_for(consignment, documents):
            conflicts.append(
                ConsistencyConflict(
                    conflict_id=f"missing_certificate:{consignment['id']}",
                    conflict_type="missing_certificate",
                    severity=ConflictSeverity.HIGH,
                    title="Missing lithium battery safety certificate",
                    details=(
                        f"{consignment['product_name']} has no extracted safety certificate "
                        "linked to the consignment."
                    ),
                    why_this_matters=(
                        "The UAE lithium transit rule remains unresolved until the "
                        "certificate is present as evidence."
                    ),
                    consignment_id=consignment["id"],
                    consignment_name=consignment["product_name"],
                )
            )
    return conflicts


def procedure_conflicts(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    documents: list[UploadedDocumentMetadata],
    answers: dict[str, str],
) -> list[ConsistencyConflict]:
    conflicts = []
    for consignment in shipment.get("consignments", []):
        is_uae_transit = (
            route_contains(shipment, "UAE") and consignment.get("destination_country") != "UAE"
        )
        uae_import_documents = [
            document
            for document in documents
            if document.document_type == "import_declaration"
            and document.jurisdiction == "UAE"
            and document_matches_consignment(document, consignment)
        ]
        unloaded_in_uae = [
            event["id"]
            for event in events
            if event.get("event_type") == "UNLOADED"
            and event.get("location_country") == "UAE"
            and event.get("consignment_id") == consignment["id"]
        ]
        sealed_answer = answers.get(f"sealed_onboard_uae:{consignment['id']}")

        if is_uae_transit and (uae_import_documents or unloaded_in_uae or sealed_answer == "no"):
            conflicts.append(
                ConsistencyConflict(
                    conflict_id=f"procedure_conflict:{consignment['id']}",
                    conflict_type="transit_import_procedure_conflict",
                    severity=ConflictSeverity.CRITICAL,
                    title="Transit versus import procedure conflict",
                    details=(
                        f"{consignment['product_name']} is bound for "
                        f"{consignment['destination_country']} but has UAE import "
                        "or unload signals."
                    ),
                    why_this_matters=(
                        "Applying import treatment to transit cargo would trigger the wrong "
                        "jurisdictional obligations."
                    ),
                    consignment_id=consignment["id"],
                    consignment_name=consignment["product_name"],
                    document_ids=[document.document_id for document in uae_import_documents],
                    event_ids=unloaded_in_uae,
                )
            )
    return conflicts


def route_conflicts(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[ConsistencyConflict]:
    conflicts = []
    route_legs = sorted(shipment.get("route_legs", []), key=lambda leg: leg["sequence_number"])
    for previous_leg, next_leg in zip(route_legs, route_legs[1:], strict=False):
        if previous_leg.get("destination_country") != next_leg.get("origin_country"):
            conflicts.append(
                ConsistencyConflict(
                    conflict_id=(f"route_gap:{previous_leg['id']}:{next_leg['id']}"),
                    conflict_type="route_inconsistency",
                    severity=ConflictSeverity.HIGH,
                    title="Route leg sequence is inconsistent",
                    details=(
                        f"Leg {previous_leg['sequence_number']} ends in "
                        f"{previous_leg['destination_country']} but leg "
                        f"{next_leg['sequence_number']} starts in {next_leg['origin_country']}."
                    ),
                    why_this_matters=(
                        "Route gaps can cause the checker to apply the wrong transit "
                        "or import rules."
                    ),
                )
            )

    route_countries = countries_on_route(shipment)
    for event in events:
        location_country = event.get("location_country")
        if location_country and location_country not in route_countries:
            conflicts.append(
                ConsistencyConflict(
                    conflict_id=f"event_route:{event['id']}",
                    conflict_type="route_inconsistency",
                    severity=ConflictSeverity.MEDIUM,
                    title="Event location is outside planned route",
                    details=(
                        f"{event['event_type']} occurred in {location_country}, "
                        "which is not in the planned route."
                    ),
                    why_this_matters=(
                        "Unexpected event locations can introduce unplanned jurisdictional checks."
                    ),
                    consignment_id=event.get("consignment_id"),
                    event_ids=[event["id"]],
                )
            )
    return conflicts


def grouped_documents(
    documents: list[UploadedDocumentMetadata],
) -> dict[str, list[UploadedDocumentMetadata]]:
    groups: dict[str, list[UploadedDocumentMetadata]] = defaultdict(list)
    for document in documents:
        groups[document.consignment_id or "shipment"].append(document)
    return groups


def field_values(documents: list[UploadedDocumentMetadata], *field_names: str) -> list[str]:
    values = []
    for document in documents:
        for field_name in field_names:
            value = extracted_field(document, field_name)
            existing_values = {normalize_text(item) for item in values}
            if value is not None and normalize_text(value) not in existing_values:
                values.append(str(value).strip())
    return values


def numeric_field_values(
    documents: list[UploadedDocumentMetadata],
    *field_names: str,
) -> dict[str, Decimal]:
    values = {}
    for document in documents:
        for field_name in field_names:
            parsed = to_decimal(extracted_field(document, field_name))
            if parsed is not None:
                values[document.document_id] = parsed
    return values


def extracted_field(document: UploadedDocumentMetadata, field_name: str) -> Any:
    extracted_fields = document.metadata.get("extracted_fields")
    if isinstance(extracted_fields, dict) and field_name in extracted_fields:
        return extracted_fields[field_name]
    return document.metadata.get(field_name)


def domestic_location_conflicts(shipment, documents):
    conflicts = []
    for document in documents:
        item = next(
            (
                item
                for item in shipment.get("consignments", [])
                if item["id"] == document.consignment_id
            ),
            None,
        )
        expected = {"origin_state": shipment["domestic"]["origin"]["state"]}
        if item and item.get("domestic"):
            expected["destination_state"] = item["domestic"]["destination"]["state"]
        for field, value in expected.items():
            actual = extracted_field(document, field)
            if actual and str(actual).strip().casefold() != value.casefold():
                conflicts.append(
                    conflict(
                        shipment,
                        document.consignment_id or "shipment",
                        [document],
                        "domestic_location_mismatch",
                        ConflictSeverity.HIGH,
                        "Document state conflicts with shipment",
                        f"{field}: document reports {actual}; shipment records {value}.",
                        "Dispatch and delivery states determine domestic procedure applicability.",
                    )
                )
    return conflicts


def conflict(
    shipment: dict[str, Any],
    group_key: str,
    documents: list[UploadedDocumentMetadata],
    conflict_type: str,
    severity: ConflictSeverity,
    title: str,
    details: str,
    why_this_matters: str,
) -> ConsistencyConflict:
    consignment = consignment_for_group(shipment, group_key)
    return ConsistencyConflict(
        conflict_id=f"{conflict_type}:{group_key}:{hash_key(details)}",
        conflict_type=conflict_type,
        severity=severity,
        title=title,
        details=details,
        why_this_matters=why_this_matters,
        consignment_id=consignment["id"] if consignment else None,
        consignment_name=consignment["product_name"] if consignment else None,
        document_ids=[document.document_id for document in documents],
    )


def consignment_for_group(shipment: dict[str, Any], group_key: str) -> dict[str, Any] | None:
    if group_key == "shipment":
        return None
    return next(
        (
            consignment
            for consignment in shipment.get("consignments", [])
            if consignment["id"] == group_key
        ),
        None,
    )


def route_contains(shipment: dict[str, Any], country: str) -> bool:
    return country in countries_on_route(shipment)


def countries_on_route(shipment: dict[str, Any]) -> set[str]:
    countries = {shipment.get("exporter_country"), shipment.get("importer_country")}
    for leg in shipment.get("route_legs", []):
        countries.add(leg.get("origin_country"))
        countries.add(leg.get("destination_country"))
    return {country for country in countries if country}


def has_event(
    events: list[dict[str, Any]],
    event_type: str,
    location_country: str,
    consignment_id: str | None,
) -> bool:
    for event in events:
        if event.get("event_type") != event_type:
            continue
        if event.get("location_country") != location_country:
            continue
        if consignment_id is not None and event.get("consignment_id") != consignment_id:
            continue
        return True
    return False


def has_certificate_for(
    consignment: dict[str, Any],
    documents: list[UploadedDocumentMetadata],
) -> bool:
    accepted_types = {"safety_certificate", "lithium_battery_safety_certificate"}
    for document in documents:
        if document.document_type not in accepted_types:
            continue
        if not document_matches_consignment(document, consignment):
            continue
        status = str(document.metadata.get("verification_status", "EXTRACTED")).upper()
        if status in {"EXTRACTED", "VERIFIED"}:
            return True
    return False


def document_matches_consignment(
    document: UploadedDocumentMetadata,
    consignment: dict[str, Any],
) -> bool:
    return document.consignment_id in (None, consignment["id"])


def is_lithium(consignment: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(consignment.get("product_name", "")),
            str(consignment.get("product_description", "")),
        ]
    ).lower()
    return "lithium" in text and "batter" in text


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    cleaned = re.sub(r"\b[A-Z]{3}\b", "", str(value).upper())
    cleaned = cleaned.replace(",", "").strip()
    try:
        parsed = Decimal(cleaned)
        return parsed if parsed.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def normalize_text(value: Any) -> str:
    return str(value or "").strip().casefold()


def display_label(value: str) -> str:
    return value.replace("_", " ")


def format_numeric_map(values: dict[str, Decimal]) -> str:
    return ", ".join(f"{document_id}={value}" for document_id, value in values.items())


def stable_question_id(attribute_key: str) -> str:
    return f"q-{attribute_key.replace(':', '-').replace('_', '-')}"


def impact_for_status(status) -> int:
    if str(status) == "NON_COMPLIANT":
        return 95
    if str(status) == "CONDITIONALLY_COMPLIANT":
        return 80
    return 60


def severity_rank(severity: ConflictSeverity) -> int:
    order = {
        ConflictSeverity.CRITICAL: 0,
        ConflictSeverity.HIGH: 1,
        ConflictSeverity.MEDIUM: 2,
        ConflictSeverity.LOW: 3,
    }
    return order[severity]


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
