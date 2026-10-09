import math
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ComplianceStatus(StrEnum):
    COMPLIANT = "COMPLIANT"
    CONDITIONALLY_COMPLIANT = "CONDITIONALLY_COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class UploadedDocumentMetadata(BaseModel):
    document_id: str
    document_type: str
    filename: str | None = None
    consignment_id: str | None = None
    shipment_event_id: str | None = None
    jurisdiction: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComplianceEvaluationRequest(BaseModel):
    uploaded_documents: list[UploadedDocumentMetadata] = Field(default_factory=list)


class RuleOutcome(BaseModel):
    status: ComplianceStatus
    violation: str
    recommended_action: str


class ComplianceRule(BaseModel):
    rule_id: str
    title: str
    jurisdiction: str
    procedure_type: str
    effective_from: str
    effective_to: str | None = None
    source_url: str
    version: str
    conditions: dict[str, Any]
    required_documents: list[str]
    outcome_if_failed: RuleOutcome

    @model_validator(mode="after")
    def validate_effective_dates(self):
        if self.conditions.get("scope") == "india_domestic":
            unknown = set(self.conditions) - {
                "scope",
                "consignment_value_above",
                "requires_eway_confirmation",
            }
            if unknown:
                raise ValueError(f"Unsupported domestic rule conditions: {sorted(unknown)}")
            if self.procedure_type not in {"domestic", "interstate", "intrastate"}:
                raise ValueError("Domestic rules require a domestic movement procedure")
            minimum = self.conditions.get("consignment_value_above")
            if minimum is not None and (
                type(minimum) not in (int, float) or not math.isfinite(minimum) or minimum < 0
            ):
                raise ValueError("Consignment threshold must be a finite nonnegative number")
            if (
                "requires_eway_confirmation" in self.conditions
                and type(self.conditions["requires_eway_confirmation"]) is not bool
            ):
                raise ValueError("E-way confirmation condition must be boolean")
        start = date.fromisoformat(self.effective_from)
        if self.effective_to and date.fromisoformat(self.effective_to) < start:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class ApplicableRuleResult(BaseModel):
    rule_id: str
    title: str
    jurisdiction: str
    procedure_type: str
    version: str
    effective_from: str
    effective_to: str | None = None
    source_url: str
    required_documents: list[str] = Field(default_factory=list)
    status: ComplianceStatus
    missing_documents: list[str] = Field(default_factory=list)
    supporting_document_ids: list[str] = Field(default_factory=list)
    shipment_event_id: str | None = None
    violation: str | None = None
    recommended_action: str | None = None


class ConsignmentComplianceResult(BaseModel):
    consignment_id: str
    product_name: str
    jurisdiction: str
    procedure_type: str
    status: ComplianceStatus
    applicable_rules: list[ApplicableRuleResult] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    recommended_action: str


class ComplianceAssessmentResult(BaseModel):
    shipment_id: str
    status: ComplianceStatus
    applicable_rules: list[ApplicableRuleResult] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    recommended_action: str
    consignment_results: list[ConsignmentComplianceResult] = Field(default_factory=list)


class ComplianceAssessmentRead(BaseModel):
    id: str
    shipment_id: str
    job_id: str | None
    status: ComplianceStatus
    created_at: datetime
    result: ComplianceAssessmentResult


class ConflictSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConsistencyConflict(BaseModel):
    conflict_id: str
    conflict_type: str
    severity: ConflictSeverity
    title: str
    details: str
    why_this_matters: str
    consignment_id: str | None = None
    consignment_name: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class ConsistencyCheckRequest(BaseModel):
    uploaded_documents: list[UploadedDocumentMetadata] = Field(default_factory=list)


class ConsistencyCheckRead(BaseModel):
    shipment_id: str
    checked_at: datetime
    conflicts: list[ConsistencyConflict] = Field(default_factory=list)


class InformationGainQuestionRead(BaseModel):
    question_id: str
    shipment_id: str
    consignment_id: str | None = None
    attribute_key: str
    question: str
    impact_score: int
    affects_rules: list[str] = Field(default_factory=list)
    why_this_matters: str
    answer_options: list[str] = Field(default_factory=list)


class QuestionAnswerRequest(BaseModel):
    answer: str
    uploaded_documents: list[UploadedDocumentMetadata] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionAnswerRead(BaseModel):
    question: InformationGainQuestionRead
    answer: str
    assessment: ComplianceAssessmentRead


class RouteOptimizationRequest(BaseModel):
    uploaded_documents: list[UploadedDocumentMetadata] = Field(default_factory=list)


class RouteOptionRead(BaseModel):
    route_id: str
    label: str
    description: str
    countries: list[str]
    per_consignment_paths: dict[str, list[str]]
    is_current_route: bool
    legal_status: str
    compliance_status: ComplianceStatus
    score: float
    estimated_duty: float
    fta_eligible: bool
    risk_score: float
    estimated_delay_hours: float
    required_documents: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    invalid_reasons: list[str] = Field(default_factory=list)
    corrective_actions: list[str] = Field(default_factory=list)
    is_recommended: bool = False


class RouteOptimizationRead(BaseModel):
    shipment_id: str
    generated_at: datetime
    recommended_route_id: str | None = None
    options: list[RouteOptionRead] = Field(default_factory=list)


class RegulationCreateRequest(BaseModel):
    rule: ComplianceRule | None = None


class RegulationRead(BaseModel):
    id: str
    status: str
    rule: ComplianceRule
    created_at: datetime
    published_at: datetime | None = None


class RegulationPublishRead(BaseModel):
    regulation: RegulationRead
    message: str


class ImpactAnalysisRequest(BaseModel):
    regulation_ids: list[str] = Field(default_factory=list)
    uploaded_documents: list[UploadedDocumentMetadata] = Field(default_factory=list)


class RegulationSummary(BaseModel):
    id: str
    rule_id: str
    title: str
    jurisdiction: str
    procedure_type: str
    version: str


class ShipmentImpactRead(BaseModel):
    shipment_id: str
    shipment_reference: str
    previous_status: ComplianceStatus
    new_status: ComplianceStatus
    triggering_regulation: RegulationSummary
    corrective_action: str
    affected_consignment_ids: list[str] = Field(default_factory=list)
    route_recommendation: RouteOptionRead | None = None
    assessment: ComplianceAssessmentRead


class ImpactAnalysisRead(BaseModel):
    generated_at: datetime
    analyzed_regulations: list[RegulationSummary] = Field(default_factory=list)
    impacted_shipments: list[ShipmentImpactRead] = Field(default_factory=list)


class PrincipalRead(BaseModel):
    actor_id: str
    role: str


class AuditLogRead(BaseModel):
    id: str
    actor_id: str
    role: str
    action: str
    resource_type: str
    resource_id: str | None
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    error: str
    detail: Any
    trace_id: str | None = None


class ReportFormat(StrEnum):
    HTML = "html"
    PDF = "pdf"


class DemoScenarioRead(BaseModel):
    scenario_id: str
    title: str
    summary: str
    shipment_reference: str
    route: list[str]
    consignments: list[str]
    walkthrough_steps: list[str]
