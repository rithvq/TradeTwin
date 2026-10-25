"""Immutable calculation evidence, separate from action-bound dispatch authority."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, TS, Authored, ConsignmentRecord, TradeBase


class RuleDependencySpecification(Authored, TradeBase):
    __tablename__ = "compliance_rule_dependency_specifications"
    __table_args__ = (UniqueConstraint("rule_id", "compiler_hash"),)
    rule_id: Mapped[str] = mapped_column(ForeignKey("regulation_rules.id"))
    compiler_hash: Mapped[str] = mapped_column(String(64))
    specification_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))
    reusable: Mapped[bool] = mapped_column(Boolean)


class DependencyScopeEpoch(TradeBase):
    __tablename__ = "compliance_dependency_scope_epochs"
    scope_key: Mapped[str] = mapped_column(String(250), primary_key=True)
    generation_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    epoch: Mapped[int] = mapped_column(BigInteger)
    last_change_code: Mapped[str] = mapped_column(String(100))
    changed_at: Mapped[datetime] = mapped_column(TS)


class RuleComputation(ConsignmentRecord, TradeBase):
    __tablename__ = "compliance_rule_computations"
    __table_args__ = (
        Index(
            "ix_rule_calculation_lookup",
            "consignment_id",
            "action",
            "execution_mode",
            "rule_id",
            "dependency_digest",
        ),
    )
    origin_evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    rule_id: Mapped[str] = mapped_column(ForeignKey("regulation_rules.id"))
    specification_id: Mapped[str] = mapped_column(ForeignKey(RuleDependencySpecification.id))
    action: Mapped[str] = mapped_column(String(30))
    execution_mode: Mapped[str] = mapped_column(String(20))
    engine_manifest_hash: Mapped[str] = mapped_column(String(64))
    dependency_digest: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict] = mapped_column(JSON_TYPE)
    supporting_references_json: Mapped[list] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))
    reusable: Mapped[bool] = mapped_column(Boolean)
    valid_from: Mapped[datetime] = mapped_column(TS)
    valid_until: Mapped[datetime] = mapped_column(TS)


class DependencyWitness(Authored, TradeBase):
    __tablename__ = "compliance_dependency_witnesses"
    computation_id: Mapped[str] = mapped_column(ForeignKey(RuleComputation.id), index=True)
    witness_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


class EvaluationComputationLink(Authored, TradeBase):
    __tablename__ = "compliance_evaluation_computation_links"
    __table_args__ = (UniqueConstraint("evaluation_id", "rule_id"),)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("regulation_rules.id"))
    requirement_id: Mapped[str] = mapped_column(ForeignKey("compliance_requirements.id"))
    computation_id: Mapped[str] = mapped_column(ForeignKey(RuleComputation.id))
    disposition: Mapped[str] = mapped_column(String(20))
    reason_codes_json: Mapped[list] = mapped_column(JSON_TYPE)


class EvaluationExecution(Authored, TradeBase):
    __tablename__ = "compliance_evaluation_executions"
    __table_args__ = (UniqueConstraint("evaluation_id"),)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    requested_strategy: Mapped[str] = mapped_column(String(20))
    authoritative_strategy: Mapped[str] = mapped_column(String(30))
    engine_manifest_json: Mapped[dict] = mapped_column(JSON_TYPE)
    encrypted_capture_json: Mapped[dict] = mapped_column(JSON_TYPE)
    capture_hash: Mapped[str] = mapped_column(String(64))
    semantic_hash: Mapped[str] = mapped_column(String(64))
    trace_json: Mapped[dict] = mapped_column(JSON_TYPE)


TABLES = [
    RuleDependencySpecification,
    DependencyScopeEpoch,
    RuleComputation,
    DependencyWitness,
    EvaluationComputationLink,
    EvaluationExecution,
]
IMMUTABLE_TABLES = [m.__tablename__ for m in TABLES if m is not DependencyScopeEpoch]
