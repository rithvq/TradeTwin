"""Retained inputs and assessments; only lifecycle heads are mutable."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.freight.models import Snapshot
from app.trades.models import JSON_TYPE, Mutable, Record, TradeBase

TS = DateTime(timezone=True)


class Connection(Mutable, TradeBase):
    __tablename__ = "corridor_source_connections"
    owner_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    provider_code: Mapped[str] = mapped_column(String(50))
    environment: Mapped[str] = mapped_column(String(20), index=True)
    source_kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")
    connection_json: Mapped[dict] = mapped_column(JSON_TYPE)


class FetchAttempt(Record, TradeBase):
    __tablename__ = "corridor_source_fetch_attempts"
    source_connection_id: Mapped[str] = mapped_column(ForeignKey(Connection.id), index=True)
    result: Mapped[str] = mapped_column(String(30))
    attempt_json: Mapped[dict] = mapped_column(JSON_TYPE)


class SourceItem(Snapshot, TradeBase):
    __tablename__ = "corridor_source_items"
    __table_args__ = (
        UniqueConstraint("source_connection_id", "provider_item_key", "content_hash"),
    )
    source_connection_id: Mapped[str] = mapped_column(ForeignKey(Connection.id), index=True)
    provider_item_key: Mapped[str] = mapped_column(String(300))
    artifact_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_operational_attachments.id")
    )
    retrieved_at: Mapped[datetime] = mapped_column(TS)
    source_issued_at: Mapped[datetime | None] = mapped_column(TS)
    item_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Policy(Snapshot, TradeBase):
    __tablename__ = "corridor_effect_policy_revisions"
    environment: Mapped[str] = mapped_column(String(20), index=True)
    policy_code: Mapped[str] = mapped_column(String(100))
    effective_from: Mapped[datetime] = mapped_column(TS)
    effective_until: Mapped[datetime] = mapped_column(TS)
    policy_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Mapping(Snapshot, TradeBase):
    __tablename__ = "corridor_source_mapping_revisions"
    environment: Mapped[str] = mapped_column(String(20), index=True)
    endpoint_contract_version: Mapped[str] = mapped_column(String(50))
    effective_from: Mapped[datetime] = mapped_column(TS)
    effective_until: Mapped[datetime] = mapped_column(TS)
    mapping_json: Mapped[dict] = mapped_column(JSON_TYPE)


class GovernanceAction(Record, TradeBase):
    __tablename__ = "corridor_governance_actions"
    __table_args__ = (
        UniqueConstraint("policy_revision_id", "sequence_number"),
        UniqueConstraint("mapping_revision_id", "sequence_number"),
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    policy_revision_id: Mapped[str | None] = mapped_column(ForeignKey(Policy.id), index=True)
    mapping_revision_id: Mapped[str | None] = mapped_column(ForeignKey(Mapping.id), index=True)
    action: Mapped[str] = mapped_column(String(30))
    content_hash: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    reason: Mapped[str] = mapped_column(String(2000))


class Incident(Mutable, TradeBase):
    __tablename__ = "corridor_incidents"
    environment: Mapped[str] = mapped_column(String(20), index=True)
    owner_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    consignment_id: Mapped[str | None] = mapped_column(ForeignKey("op_consignments.id"))
    visibility: Mapped[str] = mapped_column(String(30), default="ORG_ONLY")
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("corridor_event_revisions.id", use_alter=True, name="fk_corridor_current_event")
    )


class EventRevision(Snapshot, TradeBase):
    __tablename__ = "corridor_event_revisions"
    __table_args__ = (UniqueConstraint("incident_id", "revision_number"),)
    incident_id: Mapped[str] = mapped_column(ForeignKey(Incident.id), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    source_item_id: Mapped[str] = mapped_column(ForeignKey(SourceItem.id))
    event_kind: Mapped[str] = mapped_column(String(40))
    assessed_effective_from: Mapped[datetime | None] = mapped_column(TS, index=True)
    assessed_effective_until: Mapped[datetime | None] = mapped_column(TS, index=True)
    operational_review_due_at: Mapped[datetime] = mapped_column(TS, index=True)
    event_json: Mapped[dict] = mapped_column(JSON_TYPE)


class EventAction(Record, TradeBase):
    __tablename__ = "corridor_event_actions"
    __table_args__ = (UniqueConstraint("event_revision_id", "sequence_number"),)
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_revision_id: Mapped[str] = mapped_column(ForeignKey(EventRevision.id), index=True)
    action: Mapped[str] = mapped_column(String(40))
    event_hash: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    action_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Tombstone(Record, TradeBase):
    __tablename__ = "corridor_upstream_tombstones"
    __table_args__ = (UniqueConstraint("source_connection_id", "upstream_key", "message_hash"),)
    source_connection_id: Mapped[str] = mapped_column(ForeignKey(Connection.id))
    upstream_key: Mapped[str] = mapped_column(String(600), index=True)
    message_hash: Mapped[str] = mapped_column(String(64))
    source_item_id: Mapped[str] = mapped_column(ForeignKey(SourceItem.id))
    action: Mapped[str] = mapped_column(String(20))


class ScopeHead(TradeBase):
    __tablename__ = "corridor_scope_heads"
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    epoch: Mapped[int] = mapped_column(BigInteger, default=0)


class SourceHealth(TradeBase):
    __tablename__ = "corridor_source_health"
    source_connection_id: Mapped[str] = mapped_column(ForeignKey(Connection.id), primary_key=True)
    health_version: Mapped[int] = mapped_column(BigInteger, default=1)
    coverage_status: Mapped[str] = mapped_column(String(20))
    last_success_at: Mapped[datetime | None] = mapped_column(TS)
    health_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Coverage(Snapshot, TradeBase):
    __tablename__ = "corridor_coverage_snapshots"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    execution_mode: Mapped[str] = mapped_column(String(20))
    coverage_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Assessment(Snapshot, TradeBase):
    __tablename__ = "corridor_impact_assessments"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    route_plan_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("consignment_route_plan_revisions.id")
    )
    run_id: Mapped[str | None] = mapped_column(ForeignKey("tradetwin_runs.id"))
    coverage_snapshot_id: Mapped[str] = mapped_column(ForeignKey(Coverage.id))
    execution_mode: Mapped[str] = mapped_column(String(20))
    evaluated_as_of: Mapped[datetime] = mapped_column(TS)
    valid_until: Mapped[datetime] = mapped_column(TS)
    input_json: Mapped[dict] = mapped_column(JSON_TYPE)
    result_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ImpactItem(Record, TradeBase):
    __tablename__ = "corridor_impact_items"
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id), index=True)
    event_revision_id: Mapped[str] = mapped_column(ForeignKey(EventRevision.id))
    policy_revision_id: Mapped[str | None] = mapped_column(ForeignKey(Policy.id))
    impact_json: Mapped[dict] = mapped_column(JSON_TYPE)


class RecoveryCase(Mutable, TradeBase):
    __tablename__ = "corridor_recovery_cases"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id))
    status: Mapped[str] = mapped_column(String(30), default="DETECTED")
    protection_state: Mapped[str] = mapped_column(String(30))
    case_json: Mapped[dict] = mapped_column(JSON_TYPE)


class DriverResponse(Snapshot, TradeBase):
    __tablename__ = "corridor_driver_responses"
    recovery_case_id: Mapped[str] = mapped_column(ForeignKey(RecoveryCase.id), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    action: Mapped[str] = mapped_column(String(40))
    observed_at: Mapped[datetime] = mapped_column(TS)
    response_json: Mapped[dict] = mapped_column(JSON_TYPE)


class MotionHead(TradeBase):
    __tablename__ = "corridor_motion_heads"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), primary_key=True)
    latest_response_id: Mapped[str | None] = mapped_column(ForeignKey(DriverResponse.id))
    motion: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    stationary_epoch: Mapped[int] = mapped_column(BigInteger, default=0)


TABLES = [
    Connection,
    FetchAttempt,
    SourceItem,
    Policy,
    Mapping,
    GovernanceAction,
    Incident,
    EventRevision,
    EventAction,
    Tombstone,
    ScopeHead,
    SourceHealth,
    Coverage,
    Assessment,
    ImpactItem,
    RecoveryCase,
    DriverResponse,
    MotionHead,
]
IMMUTABLE_TABLES = [
    m.__tablename__
    for m in TABLES
    if m not in {Connection, Incident, ScopeHead, SourceHealth, RecoveryCase, MotionHead}
]
