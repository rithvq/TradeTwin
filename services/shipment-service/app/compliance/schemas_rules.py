from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.trades.schemas import Schema

from .expression import validate
from .schemas_facts import Code, Hash, Ids, Mode, Note, State, Timestamp

OFFICIAL_HOSTS = {
    "taxinformation.cbic.gov.in",
    "cbic.gov.in",
    "gstcouncil.gov.in",
    "docs.ewaybillgst.gov.in",
    "services.gst.gov.in",
    "einvoice6.gst.gov.in",
    "www.pib.gov.in",
    "pib.gov.in",
}


class SourceInput(Schema):
    source_status: Literal["ACTIVE", "HELD", "WITHDRAWN", "UNKNOWN"] = "UNKNOWN"
    source_origin: Literal["OFFICIAL_SNAPSHOT_PROVIDED", "SIMULATION_FIXTURE"] = (
        "OFFICIAL_SNAPSHOT_PROVIDED"
    )
    source_kind: Literal[
        "ACT", "RULE", "NOTIFICATION", "CIRCULAR", "PORTAL_ADVISORY", "OFFICIAL_API_CONTRACT"
    ]
    issuer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    official_url: str = Field(max_length=2000)
    document_number: str | None = Field(None, max_length=100)
    publication_date: date | None = None
    effective_from: Timestamp | None = None
    effective_until: Timestamp | None = None
    jurisdictions: list[str] = Field(min_length=1, max_length=40)
    retrieved_at: Timestamp
    snapshot_attachment_id: UUID
    source_sha256: Hash
    supersedes_source_id: UUID | None = None
    interpretation_note: str = Field(min_length=1, max_length=5000)

    @field_validator("official_url")
    @classmethod
    def official(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in OFFICIAL_HOSTS
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Use an approved official HTTPS source, not news or an arbitrary fetch URL"
            )
        return value


class Expression(Schema):
    expression: dict

    @field_validator("expression")
    @classmethod
    def grammar(cls, value):
        return validate(value)


class ProofPolicy(Schema):
    policy: Literal["AUTHORISED_LIVE_ONLY", "AUTHORISED_LIVE_OR_REVIEWED_MANUAL", "SIMULATED_ONLY"]
    maximum_age_seconds: int = Field(gt=0, le=86400)
    required_target_identifiers: list[Code] = Field(min_length=1, max_length=10)
    required_observed_fields: list[Code] = Field(min_length=1, max_length=40)
    supporting_evidence_required: bool = True
    manual_review_permission: Code | None = None
    limitations: list[str] = Field(default_factory=list, max_length=20)


class RuleInput(Schema):
    rule_code: Code
    rule_version: Code = Field(max_length=50)
    requirement_code: Code
    rule_class: Literal["LEGAL_REQUIREMENT", "PORTAL_CONTROL", "APPLICATION_POLICY"] = Field(
        alias="class"
    )
    date_basis: Literal["ACTION_TIME", "INVOICE_DATE", "OBSERVATION_TIME", "PLANNED_ARRIVAL_TIME"]
    observation_check_type: (
        Literal["GSTIN_AUTHORITY_LOOKUP", "IRN_LIVE_STATUS", "EWB_AUTHORITY_LOOKUP"] | None
    ) = None
    effective_from: Timestamp
    effective_until: Timestamp | None = None
    applicability_expression: dict
    satisfaction_expression: dict
    dependency_paths: list[Code] = Field(min_length=1, max_length=100)
    required_evidence_types: list[Code] = Field(default_factory=list, max_length=40)
    allowed_proof_methods: list[Code] = Field(default_factory=list, max_length=20)
    mandatory: bool
    severity: Literal["BLOCKER", "WARNING", "INFO"]
    waivable_warning: bool = False
    source_ids: Ids = Field(min_length=1)
    explanation_template: str = Field(min_length=1, max_length=2000)
    remedy_codes: list[Code] = Field(default_factory=list, max_length=20)

    @field_validator("applicability_expression", "satisfaction_expression")
    @classmethod
    def expressions(cls, value):
        return validate(value)

    @model_validator(mode="after")
    def warning(self):
        if self.date_basis == "OBSERVATION_TIME" and not self.observation_check_type:
            raise ValueError("Observation-time rules need an explicit authority check type")
        if self.waivable_warning and (
            self.rule_class != "APPLICATION_POLICY" or self.severity != "WARNING" or self.mandatory
        ):
            raise ValueError("Only nonmandatory APPLICATION_POLICY warnings may be acknowledged")
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("Rule validity interval is empty")
        return self


class PackInput(Schema):
    family_code: Code
    version: Code = Field(max_length=50)
    environment: Mode
    title: str = Field(min_length=1, max_length=300)
    input_schema_version: Literal["COMPLIANCE_FACTS_V1"]
    rule_schema_version: Literal["PH4_TYPED_RULES_V1"]
    supported_scope_predicate: dict
    excluded_scope_predicate: dict
    coverage_dimensions: dict[str, Literal["COVERED", "NOT_ASSESSED", "UNSUPPORTED"]]
    effective_from: Timestamp
    effective_until: Timestamp | None = None
    source_ids: Ids = Field(min_length=1)
    limitations: list[Annotated[str, Field(max_length=1000)]] = Field(min_length=1, max_length=40)
    default_authorisation_ttl_seconds: int = Field(900, gt=0, le=900)
    proof_policy: dict[str, ProofPolicy]
    separation_of_duties_policy: dict[str, Literal[True]]
    supported_scope_codes: list[Code] = Field(min_length=1, max_length=40)
    supported_commodity_codes: list[Code] = Field(min_length=1, max_length=40)
    supported_corridors: list[Annotated[list[State], Field(min_length=2, max_length=22)]] = Field(
        min_length=1, max_length=100
    )
    supplier_exclusion_codes: list[Code] = Field(default_factory=lambda: ["NONE_CLAIMED"])
    exception_codes: list[Code] = Field(default_factory=list)
    rules: list[RuleInput] = Field(min_length=1, max_length=100)

    @field_validator("supported_scope_predicate", "excluded_scope_predicate")
    @classmethod
    def scope(cls, value):
        return validate(value)

    @model_validator(mode="after")
    def pack(self):
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("Pack validity interval is empty")
        if len({r.rule_code for r in self.rules}) != len(self.rules):
            raise ValueError("Rule codes must be unique in a pack")
        if any(set(r.source_ids) - set(self.source_ids) for r in self.rules):
            raise ValueError("Rules may reference this pack's sources only")
        if self.environment == "PRODUCTION" and any(
            p.policy == "SIMULATED_ONLY" for p in self.proof_policy.values()
        ):
            raise ValueError("Production proof policy cannot accept simulated observations")
        required = {
            "independent_facts_review",
            "independent_release_review",
            "independent_publication",
        }
        if not required <= set(self.separation_of_duties_policy):
            raise ValueError("Pack must retain the independent review guardrails")
        return self


class ConflictInput(Schema):
    source_ids: Ids = Field(min_length=2)
    issue: Note
    scope: dict


class ConflictResolution(Schema):
    resolution: Note
    governing_source_ids: Ids = Field(min_length=1)
    reason: Note


class PackTestInput(Schema):
    pack_hash: Hash
    test_suite_id: Literal["PH4_REQUIRED_BOUNDARIES_V1"]


class PackReview(Schema):
    pack_hash: Hash
    passed_test_run_id: UUID
    reason: Note


class PublishInput(Schema):
    pack_hash: Hash
    review_approval_event_id: UUID
