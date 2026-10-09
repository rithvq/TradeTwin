from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.document_client import create_evidence_records, get_uploaded_documents, merge_documents
from app.evaluator import evaluate_compliance, load_rules, unique_ordered
from app.models import ComplianceAssessment, RegulationVersion
from app.optimizer import optimize_routes
from app.regulatory_sources import ensure_source_review
from app.schemas import (
    ComplianceAssessmentRead,
    ComplianceAssessmentResult,
    ComplianceRule,
    ImpactAnalysisRead,
    ImpactAnalysisRequest,
    RegulationCreateRequest,
    RegulationPublishRead,
    RegulationRead,
    RegulationSummary,
    RouteOptionRead,
    RuleOutcome,
    ShipmentImpactRead,
)
from app.shipment_client import get_shipment_context, list_shipments


def create_regulation_version(
    db: Session,
    payload: RegulationCreateRequest | None = None,
) -> RegulationRead:
    rule = payload.rule if payload and payload.rule else demo_domestic_rule()
    existing = (
        db.query(RegulationVersion)
        .filter(
            RegulationVersion.rule_id == rule.rule_id,
            RegulationVersion.version == rule.version,
        )
        .first()
    )
    if existing is not None:
        return to_regulation_read(existing)

    regulation = RegulationVersion(
        rule_id=rule.rule_id,
        title=rule.title,
        jurisdiction=rule.jurisdiction,
        procedure_type=rule.procedure_type,
        version=rule.version,
        status="DRAFT",
        rule_payload=rule.model_dump(mode="json"),
    )
    db.add(regulation)
    db.commit()
    db.refresh(regulation)
    return to_regulation_read(regulation)


def publish_regulation_version(db: Session, regulation_id: str) -> RegulationPublishRead:
    regulation = db.get(RegulationVersion, regulation_id)
    if regulation is None:
        raise RegulationNotFound(regulation_id)

    if regulation.status != "PUBLISHED":
        ensure_source_review(db, regulation_id)
        regulation.status = "PUBLISHED"
        regulation.published_at = datetime.now(UTC)
        db.commit()
        db.refresh(regulation)

    return RegulationPublishRead(
        regulation=to_regulation_read(regulation),
        message="Regulation version published.",
    )


def analyze_regulation_impact(
    db: Session,
    payload: ImpactAnalysisRequest,
) -> ImpactAnalysisRead:
    triggering_regulations = selected_triggering_regulations(db, payload.regulation_ids)
    base_rules = bundled_rules()
    before_rules = [
        *base_rules,
        *published_rules(db, exclude_ids={regulation.id for regulation in triggering_regulations}),
    ]
    after_rules = [*base_rules, *published_rules(db)]
    impacted_shipments = []

    for shipment in list_shipments():
        if not is_active_or_planned(shipment):
            continue
        shipment_detail, events = get_shipment_context(shipment["id"])
        documents = merge_documents(
            payload.uploaded_documents,
            get_uploaded_documents(shipment["id"]),
        )
        previous = evaluate_compliance(shipment_detail, events, documents, before_rules)
        new = evaluate_compliance(shipment_detail, events, documents, after_rules)
        triggering_rule = first_triggering_rule(new, triggering_regulations)
        if triggering_rule is None and previous.status == new.status:
            continue

        assessment = persist_assessment(db, shipment["id"], new, documents)
        route_options = optimize_routes(shipment_detail, events, documents, after_rules)
        impacted_shipments.append(
            ShipmentImpactRead(
                shipment_id=shipment["id"],
                shipment_reference=shipment["shipment_reference"],
                previous_status=previous.status,
                new_status=new.status,
                triggering_regulation=summary_for_regulation(
                    triggering_regulations[0] if triggering_rule is None else triggering_rule
                ),
                corrective_action=corrective_action(new, route_options.options),
                affected_consignment_ids=affected_consignment_ids(new, triggering_regulations),
                route_recommendation=recommended_route(route_options.options),
                assessment=assessment,
            )
        )

    return ImpactAnalysisRead(
        generated_at=datetime.now(UTC),
        analyzed_regulations=[summary_for_regulation(item) for item in triggering_regulations],
        impacted_shipments=impacted_shipments,
    )


def published_rules(
    db: Session,
    exclude_ids: set[str] | None = None,
) -> list[ComplianceRule]:
    exclude_ids = exclude_ids or set()
    regulations = (
        db.query(RegulationVersion)
        .filter(RegulationVersion.status == "PUBLISHED")
        .order_by(RegulationVersion.published_at.asc(), RegulationVersion.created_at.asc())
        .all()
    )
    return [
        ComplianceRule.model_validate(regulation.rule_payload)
        for regulation in regulations
        if regulation.id not in exclude_ids
    ]


def load_rules_with_published(db: Session) -> list[ComplianceRule]:
    return [*bundled_rules(), *published_rules(db)]


def bundled_rules() -> list[ComplianceRule]:
    return load_rules() if settings.regulation_catalog_mode == "demo" else []


def selected_triggering_regulations(
    db: Session,
    regulation_ids: list[str],
) -> list[RegulationVersion]:
    query = db.query(RegulationVersion).filter(RegulationVersion.status == "PUBLISHED")
    if regulation_ids:
        query = query.filter(RegulationVersion.id.in_(regulation_ids))
    regulations = query.order_by(
        RegulationVersion.published_at.desc(),
        RegulationVersion.created_at.desc(),
    ).all()
    if not regulations:
        raise RegulationNotFound("latest published regulation")
    return regulations[:1] if not regulation_ids else regulations


def first_triggering_rule(
    assessment: ComplianceAssessmentResult,
    regulations: list[RegulationVersion],
) -> RegulationVersion | None:
    trigger_keys = {(regulation.rule_id, regulation.version) for regulation in regulations}
    for rule in assessment.applicable_rules:
        if (rule.rule_id, rule.version) in trigger_keys:
            return next(
                regulation
                for regulation in regulations
                if regulation.rule_id == rule.rule_id and regulation.version == rule.version
            )
    return None


def affected_consignment_ids(
    assessment: ComplianceAssessmentResult,
    regulations: list[RegulationVersion],
) -> list[str]:
    trigger_keys = {(item.rule_id, item.version) for item in regulations}
    return unique_ordered(
        consignment_result.consignment_id
        for consignment_result in assessment.consignment_results
        for rule in consignment_result.applicable_rules
        if (rule.rule_id, rule.version) in trigger_keys
    )


def persist_assessment(
    db: Session,
    shipment_id: str,
    result: ComplianceAssessmentResult,
    documents=None,
) -> ComplianceAssessmentRead:
    assessment = ComplianceAssessment(
        shipment_id=shipment_id,
        job_id=None,
        status=result.status,
        result_payload=result.model_dump(mode="json"),
    )
    db.add(assessment)
    db.flush()
    create_evidence_records(assessment.id, result, documents or [])
    db.commit()
    db.refresh(assessment)
    return ComplianceAssessmentRead(
        id=assessment.id,
        shipment_id=assessment.shipment_id,
        job_id=assessment.job_id,
        status=assessment.status,
        created_at=assessment.created_at,
        result=ComplianceAssessmentResult.model_validate(assessment.result_payload),
    )


def corrective_action(
    assessment: ComplianceAssessmentResult,
    options: list[RouteOptionRead],
) -> str:
    recommended = recommended_route(options)
    actions = [assessment.recommended_action]
    if recommended and recommended.route_id != "current-route":
        actions.append(f"Use route option: {recommended.label}.")
    if assessment.missing_documents:
        actions.extend(
            f"Upload {document_type.replace('_', ' ')}."
            for document_type in assessment.missing_documents
        )
    return "; ".join(unique_ordered(actions))


def recommended_route(options: list[RouteOptionRead]) -> RouteOptionRead | None:
    return next((option for option in options if option.is_recommended), None)


def is_active_or_planned(shipment: dict[str, Any]) -> bool:
    return shipment.get("status") not in {"DELIVERED", "CANCELLED", "ARCHIVED"}


def summary_for_regulation(regulation: RegulationVersion) -> RegulationSummary:
    return RegulationSummary(
        id=regulation.id,
        rule_id=regulation.rule_id,
        title=regulation.title,
        jurisdiction=regulation.jurisdiction,
        procedure_type=regulation.procedure_type,
        version=regulation.version,
    )


def to_regulation_read(regulation: RegulationVersion) -> RegulationRead:
    return RegulationRead(
        id=regulation.id,
        status=regulation.status,
        rule=ComplianceRule.model_validate(regulation.rule_payload),
        created_at=regulation.created_at,
        published_at=regulation.published_at,
    )


def demo_uae_transit_safety_rule() -> ComplianceRule:
    return ComplianceRule(
        rule_id="TT-UAE-LITHIUM-SAFETY-002",
        title="UAE demo lithium transit safety certificate active update",
        jurisdiction="UAE",
        procedure_type="transit",
        effective_from="2026-09-01",
        effective_to=None,
        source_url="https://example.com/rules/uae/lithium-battery-safety-v2",
        version="2026.2",
        conditions={
            "route_contains_jurisdiction": True,
            "consignment_destination_is_not_jurisdiction": True,
            "event_location_country": "UAE",
            "event_types": [
                "ARRIVED_AT_TRANSIT_PORT",
                "TRANSSHIPMENT",
                "TEMPORARY_STORAGE",
            ],
            "product_keywords": [
                "lithium battery",
                "lithium batteries",
            ],
        },
        required_documents=["lithium_battery_safety_certificate"],
        outcome_if_failed=RuleOutcome(
            status="NON_COMPLIANT",
            violation=("New UAE lithium transit safety-certificate rule is not satisfied."),
            recommended_action=(
                "Upload the lithium battery safety certificate or route the "
                "Germany-bound lithium consignment outside UAE transit."
            ),
        ),
    )


class RegulationNotFound(Exception):
    def __init__(self, regulation_id: str) -> None:
        self.regulation_id = regulation_id
        super().__init__(f"Regulation not found: {regulation_id}")


def demo_domestic_rule():
    return ComplianceRule(
        rule_id="IN-DOM-PACKING-DEMO",
        title="Demo company policy: packing list for interstate dispatch",
        jurisdiction="India",
        procedure_type="interstate",
        effective_from=datetime.now(UTC).date().isoformat(),
        version="demo-1",
        source_url="https://example.com/tradetwin/domestic-company-policy",
        conditions={"scope": "india_domestic"},
        required_documents=["packing_list"],
        outcome_if_failed=RuleOutcome(
            status="CONDITIONALLY_COMPLIANT",
            violation="Packing list required by the demo company policy is missing.",
            recommended_action=(
                "Upload the consignment packing list. "
                "This demo policy is not a government regulation."
            ),
        ),
    )
