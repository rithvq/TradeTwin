from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.domestic import domestic_routes
from app.evaluator import STATUS_SEVERITY, evaluate_compliance, load_rules, unique_ordered
from app.schemas import (
    ComplianceAssessmentResult,
    ComplianceRule,
    ComplianceStatus,
    RouteOptimizationRead,
    RouteOptionRead,
    UploadedDocumentMetadata,
)


def optimize_routes(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    uploaded_documents: list[UploadedDocumentMetadata],
    rules: list[ComplianceRule] | None = None,
    answers: dict[str, str] | None = None,
) -> RouteOptimizationRead:
    active_rules = load_rules() if rules is None else rules
    if shipment.get("domestic"):
        return domestic_routes(
            shipment, events, uploaded_documents, active_rules, evaluate_compliance, answers
        )
    if not shipment.get("consignments"):
        return RouteOptimizationRead(
            shipment_id=shipment["id"],
            generated_at=datetime.now(UTC),
            recommended_route_id=None,
            options=[],
        )
    options = [
        build_route_option(candidate, shipment, events, uploaded_documents, active_rules)
        for candidate in route_candidates(shipment)
    ]
    recommended = recommend_route(options)
    if recommended:
        options = [
            option.model_copy(update={"is_recommended": option.route_id == recommended.route_id})
            for option in options
        ]

    options.sort(
        key=lambda option: (
            not option.is_recommended,
            legal_rank(option.legal_status),
            option.score,
            option.label,
        )
    )
    return RouteOptimizationRead(
        shipment_id=shipment["id"],
        generated_at=datetime.now(UTC),
        recommended_route_id=recommended.route_id if recommended else None,
        options=options,
    )


def route_candidates(shipment: dict[str, Any]) -> list[dict[str, Any]]:
    current_path = current_route_path(shipment)
    exporter = shipment.get("exporter_country", "India")
    importer = shipment.get("importer_country", "Germany")
    consignments = shipment.get("consignments", [])

    existing_paths = {
        consignment["id"]: path_to_destination(current_path, consignment["destination_country"])
        for consignment in consignments
    }
    direct_paths = {consignment["id"]: [exporter, importer] for consignment in consignments}
    split_paths = {
        consignment["id"]: split_path_for_consignment(consignment, exporter, importer)
        for consignment in consignments
    }
    singapore_paths = {
        consignment["id"]: singapore_path_for_consignment(consignment, exporter, importer)
        for consignment in consignments
    }

    return [
        {
            "route_id": "current-route",
            "label": "Current route",
            "description": "Uses the planned route legs already attached to the shipment.",
            "per_consignment_paths": existing_paths,
            "is_current_route": True,
        },
        {
            "route_id": "direct-final-destination",
            "label": f"Direct {exporter} to {importer}",
            "description": "Moves all cargo directly to the shipment importer country.",
            "per_consignment_paths": direct_paths,
            "is_current_route": False,
        },
        {
            "route_id": "split-compliant-route",
            "label": "Split compliant movement",
            "description": (
                "Routes each consignment to its own destination and keeps Germany-bound "
                "lithium cargo out of UAE transit."
            ),
            "per_consignment_paths": split_paths,
            "is_current_route": False,
        },
        {
            "route_id": "singapore-relay",
            "label": "Singapore relay for Germany-bound cargo",
            "description": (
                "Sends Germany-bound cargo through Singapore while UAE-bound goods continue to UAE."
            ),
            "per_consignment_paths": singapore_paths,
            "is_current_route": False,
        },
    ]


def build_route_option(
    candidate: dict[str, Any],
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    uploaded_documents: list[UploadedDocumentMetadata],
    rules: list[ComplianceRule],
) -> RouteOptionRead:
    per_consignment_paths = candidate["per_consignment_paths"]
    assessment = assess_candidate_route(shipment, events, uploaded_documents, rules, candidate)
    invalid_reasons = route_invalid_reasons(shipment, per_consignment_paths, assessment)
    legal_status = "INVALID" if invalid_reasons else "VALID"
    countries = unique_ordered(
        country for path in per_consignment_paths.values() for country in path
    )
    estimated_duty = estimate_duty(shipment, per_consignment_paths)
    fta_eligible = has_fta_eligibility(per_consignment_paths)
    risk_score = estimate_risk_score(shipment, per_consignment_paths, assessment, legal_status)
    estimated_delay_hours = estimate_delay_hours(per_consignment_paths, assessment)
    score = weighted_score(
        estimated_duty,
        risk_score,
        estimated_delay_hours,
        len(assessment.missing_documents),
        legal_status,
        assessment.status,
    )

    corrective_actions = unique_ordered(
        [
            *invalid_reasons,
            *[
                f"Upload {document_type.replace('_', ' ')}."
                for document_type in assessment.missing_documents
            ],
            assessment.recommended_action,
        ]
    )

    return RouteOptionRead(
        route_id=candidate["route_id"],
        label=candidate["label"],
        description=candidate["description"],
        countries=countries,
        per_consignment_paths=per_consignment_paths,
        is_current_route=candidate["is_current_route"],
        legal_status=legal_status,
        compliance_status=assessment.status,
        score=round(score, 2),
        estimated_duty=round(estimated_duty, 2),
        fta_eligible=fta_eligible,
        risk_score=round(risk_score, 3),
        estimated_delay_hours=round(estimated_delay_hours, 1),
        required_documents=unique_ordered(
            document for rule in assessment.applicable_rules for document in rule.required_documents
        ),
        missing_documents=assessment.missing_documents,
        invalid_reasons=invalid_reasons,
        corrective_actions=corrective_actions,
    )


def assess_candidate_route(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
    uploaded_documents: list[UploadedDocumentMetadata],
    rules: list[ComplianceRule],
    candidate: dict[str, Any],
) -> ComplianceAssessmentResult:
    grouped_results = []
    for consignment in shipment.get("consignments", []):
        path = candidate["per_consignment_paths"].get(consignment["id"], [])
        temp_shipment = shipment_for_consignment_path(shipment, consignment, path)
        temp_events = events_for_path(events, consignment, path, candidate["is_current_route"])
        result = evaluate_compliance(temp_shipment, temp_events, uploaded_documents, rules)
        grouped_results.extend(result.consignment_results)

    applicable_rules = [
        rule
        for consignment_result in grouped_results
        for rule in consignment_result.applicable_rules
    ]
    missing_documents = unique_ordered(
        missing
        for consignment_result in grouped_results
        for missing in consignment_result.missing_documents
    )
    violations = unique_ordered(
        violation
        for consignment_result in grouped_results
        for violation in consignment_result.violations
    )
    actions = unique_ordered(
        result.recommended_action
        for result in grouped_results
        if result.recommended_action != "No action required."
    )
    statuses = [result.status for result in grouped_results]
    status = max(statuses, key=lambda item: STATUS_SEVERITY[item])
    return ComplianceAssessmentResult(
        shipment_id=shipment["id"],
        status=status,
        applicable_rules=applicable_rules,
        missing_documents=missing_documents,
        violations=violations,
        recommended_action="; ".join(actions) or "No action required.",
        consignment_results=grouped_results,
    )


def recommend_route(options: list[RouteOptionRead]) -> RouteOptionRead | None:
    compliant_options = [
        option
        for option in options
        if option.legal_status == "VALID" and option.compliance_status == ComplianceStatus.COMPLIANT
    ]
    if compliant_options:
        return min(compliant_options, key=lambda option: option.score)

    return None


def route_invalid_reasons(
    shipment: dict[str, Any],
    per_consignment_paths: dict[str, list[str]],
    assessment: ComplianceAssessmentResult,
) -> list[str]:
    reasons = []
    consignments = {item["id"]: item for item in shipment.get("consignments", [])}
    for consignment_id, path in per_consignment_paths.items():
        consignment = consignments[consignment_id]
        destination = consignment["destination_country"]
        if not path or path[-1] != destination:
            reasons.append(f"{consignment['product_name']} route does not end in {destination}.")

    if assessment.status == ComplianceStatus.NON_COMPLIANT:
        reasons.append("Deterministic compliance rules mark this route non-compliant.")
    return unique_ordered(reasons)


def current_route_path(shipment: dict[str, Any]) -> list[str]:
    route_legs = sorted(shipment.get("route_legs", []), key=lambda leg: leg["sequence_number"])
    if not route_legs:
        return [shipment["exporter_country"], shipment["importer_country"]]
    path = [route_legs[0]["origin_country"]]
    path.extend(leg["destination_country"] for leg in route_legs)
    return path


def path_to_destination(path: list[str], destination: str) -> list[str]:
    if destination in path:
        return path[: path.index(destination) + 1]
    return path


def split_path_for_consignment(
    consignment: dict[str, Any],
    exporter: str,
    importer: str,
) -> list[str]:
    if consignment["destination_country"] == importer:
        return [exporter, importer]
    return [exporter, consignment["destination_country"]]


def singapore_path_for_consignment(
    consignment: dict[str, Any],
    exporter: str,
    importer: str,
) -> list[str]:
    if consignment["destination_country"] == importer:
        return [exporter, "Singapore", importer]
    return [exporter, consignment["destination_country"]]


def shipment_for_consignment_path(
    shipment: dict[str, Any],
    consignment: dict[str, Any],
    path: list[str],
) -> dict[str, Any]:
    return {
        **shipment,
        "importer_country": consignment["destination_country"],
        "consignments": [consignment],
        "route_legs": route_legs_for_path(shipment["id"], path),
    }


def route_legs_for_path(shipment_id: str, path: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"candidate-leg-{sequence}",
            "shipment_id": shipment_id,
            "sequence_number": sequence,
            "origin_country": origin,
            "destination_country": destination,
            "transport_mode": "SEA",
            "carrier_name": "TradeTwin deterministic optimizer",
        }
        for sequence, (origin, destination) in enumerate(zip(path, path[1:], strict=False), 1)
    ]


def events_for_path(
    events: list[dict[str, Any]],
    consignment: dict[str, Any],
    path: list[str],
    is_current_route: bool,
) -> list[dict[str, Any]]:
    if is_current_route:
        return [
            event for event in events if event.get("consignment_id") in (None, consignment["id"])
        ]

    generated = [
        {
            "id": f"candidate-created-{consignment['id']}",
            "shipment_id": consignment["shipment_id"],
            "consignment_id": None,
            "event_type": "CREATED",
            "location_country": path[0],
            "occurred_at": "2026-01-01T00:00:00Z",
            "metadata": {"source": "route-optimizer"},
        },
        {
            "id": f"candidate-loaded-{consignment['id']}",
            "shipment_id": consignment["shipment_id"],
            "consignment_id": consignment["id"],
            "event_type": "LOADED",
            "location_country": path[0],
            "occurred_at": "2026-01-01T02:00:00Z",
            "metadata": {"source": "route-optimizer"},
        },
    ]
    for country in path[1:-1]:
        generated.append(
            {
                "id": f"candidate-arrived-{country.lower()}-{consignment['id']}",
                "shipment_id": consignment["shipment_id"],
                "consignment_id": None,
                "event_type": "ARRIVED_AT_TRANSIT_PORT",
                "location_country": country,
                "occurred_at": "2026-01-05T00:00:00Z",
                "metadata": {"source": "route-optimizer"},
            }
        )
    generated.append(
        {
            "id": f"candidate-unloaded-{consignment['id']}",
            "shipment_id": consignment["shipment_id"],
            "consignment_id": consignment["id"],
            "event_type": "UNLOADED",
            "location_country": path[-1],
            "occurred_at": "2026-01-10T00:00:00Z",
            "metadata": {"source": "route-optimizer"},
        }
    )
    return generated


def estimate_duty(
    shipment: dict[str, Any],
    per_consignment_paths: dict[str, list[str]],
) -> float:
    duty = Decimal("0")
    for consignment in shipment.get("consignments", []):
        value = Decimal(str(consignment.get("declared_value") or "0"))
        path = per_consignment_paths[consignment["id"]]
        destination = consignment["destination_country"]
        rate = Decimal("0.05") if destination == "UAE" else Decimal("0.08")
        fta_paths = (["India", "Germany"], ["India", "Singapore", "Germany"])
        if destination == "Germany" and path in fta_paths:
            rate = Decimal("0.03")
        duty += value * rate
    return float(duty)


def has_fta_eligibility(per_consignment_paths: dict[str, list[str]]) -> bool:
    return any(
        path in (["India", "Germany"], ["India", "Singapore", "Germany"])
        for path in per_consignment_paths.values()
    )


def estimate_risk_score(
    shipment: dict[str, Any],
    per_consignment_paths: dict[str, list[str]],
    assessment: ComplianceAssessmentResult,
    legal_status: str,
) -> float:
    transit_counts = [max(0, len(path) - 2) for path in per_consignment_paths.values()]
    risk = 0.2 + sum(transit_counts) * 0.04 + len(assessment.missing_documents) * 0.04
    if any("UAE" in path[1:-1] for path in per_consignment_paths.values()):
        risk += 0.12
    if lithium_transits_uae(shipment, per_consignment_paths):
        risk += 0.28
    if assessment.status == ComplianceStatus.NON_COMPLIANT:
        risk += 0.2
    if legal_status == "INVALID":
        risk += 0.25
    return min(risk, 0.99)


def estimate_delay_hours(
    per_consignment_paths: dict[str, list[str]],
    assessment: ComplianceAssessmentResult,
) -> float:
    longest_path = max(len(path) for path in per_consignment_paths.values())
    delay = 24 + (longest_path - 2) * 16 + len(assessment.missing_documents) * 4
    if any("UAE" in path[1:-1] for path in per_consignment_paths.values()):
        delay += 12
    if assessment.status == ComplianceStatus.NON_COMPLIANT:
        delay += 24
    return float(delay)


def weighted_score(
    estimated_duty: float,
    risk_score: float,
    estimated_delay_hours: float,
    missing_document_count: int,
    legal_status: str,
    compliance_status: ComplianceStatus,
) -> float:
    score = estimated_duty / 100 + risk_score * 100 + estimated_delay_hours
    score += missing_document_count * 10
    if compliance_status == ComplianceStatus.CONDITIONALLY_COMPLIANT:
        score += 35
    if compliance_status == ComplianceStatus.NON_COMPLIANT:
        score += 100
    if legal_status == "INVALID":
        score += 10000
    return score


def lithium_transits_uae(
    shipment: dict[str, Any],
    per_consignment_paths: dict[str, list[str]],
) -> bool:
    consignments = {item["id"]: item for item in shipment.get("consignments", [])}
    for consignment_id, path in per_consignment_paths.items():
        consignment = consignments[consignment_id]
        if is_lithium(consignment) and "UAE" in path[1:-1]:
            return True
    return False


def is_lithium(consignment: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(consignment.get("product_name", "")),
            str(consignment.get("product_description", "")),
        ]
    ).lower()
    return "lithium" in text and "batter" in text


def legal_rank(status: str) -> int:
    return 0 if status == "VALID" else 1


def consignment_paths_by_country(
    per_consignment_paths: dict[str, list[str]],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for consignment_id, path in per_consignment_paths.items():
        for country in path:
            grouped[country].append(consignment_id)
    return grouped
