"""Phase 7 integration records, never a second business ledger."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.freight.models import Snapshot
from app.trades.models import JSON_TYPE, Mutable, Record, TradeBase

TS = DateTime(timezone=True)


class Projection(TradeBase):
    __tablename__ = "trade_workspace_projection_heads"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    projection_version: Mapped[int] = mapped_column(BigInteger, default=1)
    source_context_version: Mapped[int] = mapped_column(BigInteger)
    source_manifest_hash: Mapped[str] = mapped_column(String(64))
    source_watermarks_json: Mapped[dict] = mapped_column(JSON_TYPE)
    operational_projection_json: Mapped[dict] = mapped_column(JSON_TYPE)
    computed_at: Mapped[datetime] = mapped_column(TS)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class TaskState(TradeBase):
    __tablename__ = "workspace_task_user_states"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"), primary_key=True)
    task_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_basis_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    seen_at: Mapped[datetime | None] = mapped_column(TS)
    snoozed_until: Mapped[datetime | None] = mapped_column(TS)
    snooze_reason: Mapped[str | None] = mapped_column(String(2000))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class ReplayRequest(Mutable, TradeBase):
    __tablename__ = "decision_replay_requests"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    replay_kind: Mapped[str] = mapped_column(String(40))
    source_manifest_hash: Mapped[str] = mapped_column(String(64))
    expected_engine_version: Mapped[str] = mapped_column(String(80))
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    requested_by_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    job_state: Mapped[str] = mapped_column(String(20), default="QUEUED")


class ReplayResult(Record, TradeBase):
    __tablename__ = "decision_replay_results"
    request_id: Mapped[str] = mapped_column(ForeignKey(ReplayRequest.id), unique=True)
    result_json: Mapped[dict] = mapped_column(JSON_TYPE)
    result_hash: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime] = mapped_column(TS)


class Comparison(Snapshot, TradeBase):
    __tablename__ = "decision_comparisons"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    left_request_id: Mapped[str] = mapped_column(ForeignKey(ReplayRequest.id))
    right_request_id: Mapped[str] = mapped_column(ForeignKey(ReplayRequest.id))
    comparison_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Bundle(Mutable, TradeBase):
    __tablename__ = "evidence_bundle_jobs"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    recipient_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    visibility: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    manifest_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    manifest_hash: Mapped[str | None] = mapped_column(String(64))
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("op_operational_attachments.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class Deployment(TradeBase):
    __tablename__ = "deployment_readiness_heads"
    deployment_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    operational_generation_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    current_manifest_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "readiness_manifest_revisions.id", use_alter=True, name="fk_readiness_current_manifest"
        )
    )
    current_qualified_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("readiness_runs.id", use_alter=True, name="fk_readiness_qualified_run")
    )
    activation_state: Mapped[str] = mapped_column(String(20), default="INACTIVE")
    controls_json: Mapped[dict] = mapped_column(JSON_TYPE)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class Manifest(Snapshot, TradeBase):
    __tablename__ = "readiness_manifest_revisions"
    deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.deployment_id), index=True)
    qualification_type: Mapped[str] = mapped_column(String(10))
    execution_mode: Mapped[str] = mapped_column(String(20))
    operational_generation_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    manifest_json: Mapped[dict] = mapped_column(JSON_TYPE)


class CheckDefinition(Snapshot, TradeBase):
    __tablename__ = "readiness_check_definition_revisions"
    __table_args__ = (UniqueConstraint("check_code", "version"),)
    check_code: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    definition_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ReadinessRun(Mutable, TradeBase):
    __tablename__ = "readiness_runs"
    manifest_revision_id: Mapped[str] = mapped_column(ForeignKey(Manifest.id))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    job_state: Mapped[str] = mapped_column(String(20), default="QUEUED")
    runner_version: Mapped[str] = mapped_column(String(50))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    qualification_outcome: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(TS)
    valid_until: Mapped[datetime | None] = mapped_column(TS)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    requested_by_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class CheckResult(Snapshot, TradeBase):
    __tablename__ = "readiness_check_results"
    run_id: Mapped[str] = mapped_column(ForeignKey(ReadinessRun.id), index=True)
    definition_revision_id: Mapped[str] = mapped_column(ForeignKey(CheckDefinition.id))
    outcome: Mapped[str] = mapped_column(String(20))
    observed_json: Mapped[dict] = mapped_column(JSON_TYPE)
    evidence_refs_json: Mapped[list] = mapped_column(JSON_TYPE)
    provenance: Mapped[str] = mapped_column(String(30))
    checked_at: Mapped[datetime] = mapped_column(TS)
    valid_until: Mapped[datetime] = mapped_column(TS)
    limitations_json: Mapped[list] = mapped_column(JSON_TYPE)


class ManualReview(Snapshot, TradeBase):
    __tablename__ = "readiness_manual_review_records"
    run_id: Mapped[str] = mapped_column(ForeignKey(ReadinessRun.id))
    definition_revision_id: Mapped[str] = mapped_column(ForeignKey(CheckDefinition.id))
    input_hash: Mapped[str] = mapped_column(String(64))
    review_statement: Mapped[str] = mapped_column(String(4000))
    evidence_refs_json: Mapped[list] = mapped_column(JSON_TYPE)


class Qualification(Record, TradeBase):
    __tablename__ = "readiness_review_decisions"
    run_id: Mapped[str] = mapped_column(ForeignKey(ReadinessRun.id), index=True)
    result_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(2000))
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    reviewer_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    valid_until: Mapped[datetime] = mapped_column(TS)


class Scope(Snapshot, TradeBase):
    __tablename__ = "pilot_scope_revisions"
    __table_args__ = (UniqueConstraint("scope_code", "version"),)
    scope_code: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    scope_json: Mapped[dict] = mapped_column(JSON_TYPE)
    valid_from: Mapped[datetime] = mapped_column(TS)
    valid_until: Mapped[datetime] = mapped_column(TS)


class ScopeApproval(Record, TradeBase):
    __tablename__ = "pilot_scope_review_approvals"
    scope_revision_id: Mapped[str] = mapped_column(ForeignKey(Scope.id))
    content_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    reason: Mapped[str] = mapped_column(String(2000))


class Admission(Record, TradeBase):
    __tablename__ = "pilot_admissions"
    __table_args__ = (UniqueConstraint("deployment_id", "consignment_id"),)
    deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.deployment_id))
    scope_revision_id: Mapped[str] = mapped_column(ForeignKey(Scope.id))
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"))
    admission_state: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    basis_json: Mapped[dict] = mapped_column(JSON_TYPE)


class DeploymentEvent(Snapshot, TradeBase):
    __tablename__ = "deployment_readiness_events"
    deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.deployment_id))
    event_type: Mapped[str] = mapped_column(String(40))
    run_id: Mapped[str | None] = mapped_column(ForeignKey(ReadinessRun.id))
    event_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Health(Snapshot, TradeBase):
    __tablename__ = "operational_health_snapshots"
    deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.deployment_id))
    component_code: Mapped[str] = mapped_column(String(50))
    observed_at: Mapped[datetime] = mapped_column(TS)
    status: Mapped[str] = mapped_column(String(20))
    health_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Rehearsal(Snapshot, TradeBase):
    __tablename__ = "restore_rehearsal_results"
    deployment_id: Mapped[str] = mapped_column(ForeignKey(Deployment.deployment_id))
    rehearsal_json: Mapped[dict] = mapped_column(JSON_TYPE)
    measured_rpo_seconds: Mapped[int | None] = mapped_column(Integer)
    measured_rto_seconds: Mapped[int | None] = mapped_column(Integer)


TABLES = [
    Projection,
    TaskState,
    ReplayRequest,
    ReplayResult,
    Comparison,
    Bundle,
    Deployment,
    Manifest,
    CheckDefinition,
    ReadinessRun,
    CheckResult,
    ManualReview,
    Qualification,
    Scope,
    ScopeApproval,
    Admission,
    DeploymentEvent,
    Health,
    Rehearsal,
]
IMMUTABLE_TABLES = [
    m.__tablename__
    for m in TABLES
    if m not in {Projection, TaskState, ReplayRequest, Bundle, Deployment, ReadinessRun, Admission}
]

from .models_demo import IMMUTABLE_TABLES as DEMO_IMMUTABLE_TABLES  # noqa: E402
from .models_demo import TABLES as DEMO_TABLES  # noqa: E402

TABLES.extend(DEMO_TABLES)
IMMUTABLE_TABLES.extend(DEMO_IMMUTABLE_TABLES)
