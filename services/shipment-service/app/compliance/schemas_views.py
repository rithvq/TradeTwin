"""Versioned public projections. Private dependency snapshots are intentionally absent."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.trades.schemas import Schema

from .schemas_facts import Action

WireTimestamp = Annotated[str, Field(json_schema_extra={"format": "date-time"})]


class ComputationRuleView(Schema):
    rule_code: str
    disposition: Literal["REUSED", "RECOMPUTED"]
    reason_codes: list[str]


class ComputationTraceView(Schema):
    evaluation_id: UUID
    status: Literal["RECORDED", "NOT_RECORDED"]
    strategy: Literal["FULL", "SHADOW", "INCREMENTAL"] | None
    authoritative_strategy: Literal["FULL", "INCREMENTAL"] | None
    rules_total: int
    rules_recomputed: int
    rules_reused: int
    shadow_rules_reused: int
    shadow_equivalent: bool | None
    invalidation_reasons: list[str]
    rules: list[ComputationRuleView]
    permission_reused: Literal[False]
    notice: str


class ReadinessView(Schema):
    schema_version: Literal["PH4_READINESS_V1"]
    consignment_id: UUID
    action: Action
    execution_mode: Literal["SIMULATION", "PRODUCTION"]
    state: str
    reasons: list[str]
    context_version: int
    evaluation: dict | None
    authorisation: dict | None
    checked_at: WireTimestamp
    label: Literal["Platform dispatch authorisation"]
    historical_notice: str | None
    operational_alerts: list[dict]


class ConstraintView(Schema):
    schema_version: Literal[1]
    contract: Literal["COMPLIANCE_CONSTRAINTS_V1"]
    trade_id: UUID
    consignment_id: UUID
    accepted_trade_revision_id: UUID
    assignment_id: UUID | None
    source_evaluation_id: UUID | None
    evaluation_hash: str | None
    dependency_hash: str | None
    context_version: int
    action: Action
    execution_mode: Literal["SIMULATION", "PRODUCTION"]
    evaluated_at: WireTimestamp | None
    valid_until: WireTimestamp | None
    freshness: Literal["CURRENT", "STALE"]
    supported_scope: bool
    coverage_dimensions: list[dict]
    declared_corridor: dict
    hard_constraints: list[dict]
    deadlines: list[dict]
    missing_inputs: list[str]
    blockers: list[str]
    limitations: list[str]
    constraint_id: str
    constraint_hash: str
    registry_epoch_manifest: dict
    dispatch_eligible: bool
    requirements: list[dict]
    allowed_transit_states: list[str] | None
    coverage: dict
    source_references: list[dict]


class EvidenceManifestView(Schema):
    schema_name: Literal["PH4_EVIDENCE_MANIFEST_V1"] = Field(alias="schema")
    evaluation_id: UUID
    evaluation_hash: str | None
    dependency_hash: str
    engine_version: str
    execution_mode: Literal["SIMULATION", "PRODUCTION"]
    action: Action
    decision: str | None
    evaluated_at: WireTimestamp | None
    valid_until: WireTimestamp | None
    freshness: str
    requirements: list[dict]
    documents: list[dict]
    sources: list[dict]
    registry_manifest: dict
    coverage: dict
    limitations: list[str]
    private_declarations: Literal["REDACTED"]
    decision_manifest_hash: str
    decision_manifest: dict
    manifest_hash: str
    graph: dict
    dispatch: dict | None = None
