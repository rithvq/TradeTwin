"""Named, bounded Phase 7 commands. Outcomes and principals are never client fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.freight.schemas import Hash, M, Timed

Module = Literal[
    "SHIPMENTS", "DOCUMENTS", "COMPLIANCE", "GRAPH", "RISK", "OPTIMIZER", "REGULATIONS", "EVIDENCE"
]
SubjectType = Literal[
    "TRADETWIN_RUN", "DISPATCH_AUTHORISATION", "RECOVERY_CASE", "FREIGHT_COMMITMENT"
]


class Reason(Timed):
    reason: str = Field(min_length=1, max_length=2000)


class TaskCommand(Reason):
    task_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    task_basis_hash: Hash
    operation: Literal["SEEN", "SNOOZE", "UNSNOOZE"]
    snoozed_until: datetime | None = None


class Subject(Timed):
    subject_type: SubjectType
    subject_id: UUID


class ReplayInput(Subject):
    replay_kind: Literal["RECORDED_DECISION", "RECOMPUTE_CAPTURED_INPUTS"]
    source_manifest_hash: Hash
    expected_engine_version: str = Field(min_length=1, max_length=80)


class ComparisonInput(Timed):
    left_subject_reference: Subject
    right_subject_reference: Subject
    expected_manifest_hashes: list[Hash] = Field(min_length=2, max_length=2)


class Recipient(Timed):
    user_id: UUID
    organisation_id: UUID


class BundleInput(Subject):
    visibility: Literal["PRIVATE_RECIPIENT", "PUBLIC_SYNTHETIC_DEMO"]
    recipient_reference: Recipient | None = None
    projection_schema_version: Literal[1] = 1


class RunInput(Timed):
    expected_manifest_hash: Hash
    check_suite_code: Literal["PRODUCT_ASSURANCE_V1"]


class ManualInput(Timed):
    check_definition_id: UUID
    input_hash: Hash
    review_statement: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[UUID] = Field(min_length=1, max_length=20)


class QualificationInput(Reason):
    result_hash: Hash
    decision: Literal["APPROVE_QUALIFICATION", "RETURN_FOR_CORRECTION"]


class ScopeInput(Timed):
    scope_code: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    organisation_ids: list[UUID] = Field(min_length=1, max_length=100)
    carrier_organisation_ids: list[UUID] = Field(min_length=1, max_length=100)
    permitted_commodity_profile_codes: list[str] = Field(min_length=1, max_length=20)
    permitted_corridor_profile_codes: list[str] = Field(min_length=1, max_length=20)
    supported_rule_pack_refs: list[UUID] = Field(min_length=1, max_length=10)
    supported_recovery_profile_codes: list[str] = Field(max_length=10)
    maximum_active_consignments: int = Field(ge=1, le=1000)
    maximum_goods_value_minor: M
    maximum_carrier_payable_minor: M
    allowed_proof_policy_refs: list[UUID] = Field(min_length=1, max_length=20)
    source_coverage_policy_refs: list[UUID] = Field(min_length=1, max_length=20)
    valid_from: datetime
    valid_until: datetime
    escalation_owner_role_refs: list[str] = Field(min_length=1, max_length=10)
    limitations: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def bounded_scope(self):
        if (
            self.valid_until <= self.valid_from
            or int(self.maximum_goods_value_minor) == 0
            or int(self.maximum_carrier_payable_minor) == 0
        ):
            raise ValueError("Pilot scope requires a positive validity window and monetary limits")
        return self


class ScopeReview(Reason):
    content_hash: Hash
    decision: Literal["APPROVE", "RETURN"]


class ActivationInput(Timed):
    qualified_run_id: UUID
    manifest_hash: Hash
    qualification_decision_id: UUID
    pilot_scope_revision_id: UUID


class PauseInput(Reason):
    pause_binding_actions: bool
    pause_movement_permissions: bool


class RestoreInput(Timed):
    registered_rehearsal_profile_code: Literal["ISOLATED_SQLITE_FENCE_V1"]


class DemoCreate(Timed):
    scenario_code: Literal["BOUNDED_JOURNEY_V1"]


class ClockAdvance(Reason):
    advance_seconds: int = Field(ge=1, le=86400)


class DemoStep(Timed):
    step_code: Literal[
        "CREATE_SIMULATION_DRAFT", "READ_INDEPENDENT_DIMENSIONS", "EXECUTABLE_RECOVERY"
    ]


class DemoRunInput(Timed):
    scenario_manifest_hash: Hash


class MeasurementInput(Timed):
    measurement_code: Literal["DEMONSTRATION_ELAPSED_TIME"]


class TaskView(Timed):
    task_key: str
    task_code: str
    trade_id: UUID
    consignment_id: UUID | None
    module_code: Module
    authoritative_subject_type: str
    authoritative_subject_id: UUID
    basis_hash: Hash
    status: Literal["OPEN", "WAITING_ON_OTHER_PARTY", "BLOCKED", "RESOLVED", "OBSOLETE"]
    priority: Literal["BLOCKER", "ACTION_REQUIRED", "INFORMATIONAL"]
    title: str
    explanation: str
    required_permission_codes: list[str]
    responsible_organisation_id: UUID | None
    responsible_role_code: str
    due_at: datetime | None
    deadline_basis: str
    deadline_source_ref: dict | None
    dependency_task_keys: list[str]
    actionable_by_current_user: bool
    action_code: str | None
    internal_screen_target: str
    expected_context_version: int | None
    expected_resource_hash: str | None
    source_refs: list[dict]
    created_from_revision_reference: UUID | None
    user_seen_at: datetime | None
    user_state_etag: str | None
    user_snoozed_until: datetime | None


class WorkspaceView(Timed):
    schema_version: Literal[1] = 1
    schema_code: Literal["TRADE_WORKSPACE_V1"] = "TRADE_WORKSPACE_V1"
    trade_id: UUID
    trade_reference: str
    execution_mode: str
    current_accepted_revision_id: UUID | None
    accepted_terms_hash: str | None
    computed_at: datetime
    source_context_version: int
    source_manifest_hash: Hash
    source_watermarks: dict
    projection_version: int
    projection_freshness: Literal["CURRENT", "STALE", "REBUILDING"]
    temporal_valid_until: datetime | None
    permitted_module_codes: list[Module]
    selected_workspace_role: str | None
    commercial: dict
    fulfilment: dict
    consignments: list[dict]
    documents: dict
    goods_finance: dict | None = None
    freight: list[dict] | None = None
    risk: dict
    tasks: list[TaskView]
    permitted_action_codes: list[str]
    source_refs: list[dict]
    limitations: list[str]
