from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, TS, Authored, ConsignmentRecord, TradeBase


class Evaluation(ConsignmentRecord, TradeBase):
    __tablename__ = "compliance_evaluations"
    __table_args__ = (Index("ix_evaluation_action", "consignment_id", "action", "created_at"),)
    action: Mapped[str] = mapped_column(String(30))
    execution_mode: Mapped[str] = mapped_column(String(20))
    context_version: Mapped[int] = mapped_column(BigInteger)
    binding_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("consignment_evidence_binding_revisions.id"), nullable=True
    )
    loading_manifest_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("loading_manifest_revisions.id"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"), nullable=True)
    job_state: Mapped[str] = mapped_column(String(20), default="QUEUED")
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dependency_hash: Mapped[str] = mapped_column(String(64))
    evaluation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registry_manifest_json: Mapped[dict] = mapped_column(JSON_TYPE)
    snapshot_json: Mapped[dict] = mapped_column(JSON_TYPE)
    coverage_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    limitations_json: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    evaluated_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(50))


class Dependency(Authored, TradeBase):
    __tablename__ = "compliance_evaluation_dependencies"
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"), index=True)
    dependency_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    freshness_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    dependency_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Requirement(Authored, TradeBase):
    __tablename__ = "compliance_requirements"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "requirement_code", "rule_id"),
        Index("ix_requirement_outcome", "evaluation_id", "severity", "outcome"),
    )
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("regulation_rules.id"))
    requirement_code: Mapped[str] = mapped_column(String(100))
    rule_class: Mapped[str] = mapped_column(String(30))
    applicability: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(20))
    mandatory: Mapped[bool] = mapped_column(Boolean)
    severity: Mapped[str] = mapped_column(String(20))
    expected_json: Mapped[dict] = mapped_column(JSON_TYPE)
    observed_json: Mapped[dict] = mapped_column(JSON_TYPE)
    evidence_refs_json: Mapped[list] = mapped_column(JSON_TYPE)
    source_ids: Mapped[list] = mapped_column(JSON_TYPE)
    explanation: Mapped[str] = mapped_column(Text)
    remedies_json: Mapped[list] = mapped_column(JSON_TYPE)


class ReviewCase(ConsignmentRecord, TradeBase):
    __tablename__ = "compliance_review_cases"
    __table_args__ = (Index("ix_compliance_open_cases", "trade_id", "consignment_id", "status"),)
    origin_evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    requirement_id: Mapped[str] = mapped_column(ForeignKey("compliance_requirements.id"))
    case_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="OPEN")
    current_resolution_action_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "compliance_case_actions.id", use_alter=True, name="fk_compliance_case_resolution"
        ),
        nullable=True,
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class CaseAction(Authored, TradeBase):
    __tablename__ = "compliance_case_actions"
    case_id: Mapped[str] = mapped_column(ForeignKey("compliance_review_cases.id"), index=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    requirement_id: Mapped[str] = mapped_column(ForeignKey("compliance_requirements.id"))
    action: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text)
    action_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ReleaseReview(Authored, TradeBase):
    __tablename__ = "compliance_review_decisions"
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"), index=True)
    evaluation_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40))
    acknowledged_warning_action_ids: Mapped[list] = mapped_column(JSON_TYPE)
    reason: Mapped[str] = mapped_column(Text)
    reviewer_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    valid_until: Mapped[datetime] = mapped_column(TS)


class Hold(ConsignmentRecord, TradeBase):
    __tablename__ = "compliance_holds"
    consignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_consignments.id"), nullable=True
    )
    __table_args__ = (Index("ix_compliance_active_hold", "trade_id", "consignment_id", "active"),)
    reason_code: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    evidence_refs_json: Mapped[list] = mapped_column(JSON_TYPE)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class HoldEvent(Authored, TradeBase):
    __tablename__ = "compliance_hold_events"
    hold_id: Mapped[str] = mapped_column(ForeignKey("compliance_holds.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    release_request_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("compliance_hold_events.id"), nullable=True
    )
