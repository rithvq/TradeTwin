from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, TS, Authored, TradeBase


class Source(Authored, TradeBase):
    __tablename__ = "regulation_sources"
    source_kind: Mapped[str] = mapped_column(String(40))
    issuer: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    official_url: Mapped[str] = mapped_column(Text)
    snapshot_attachment_id: Mapped[str] = mapped_column(ForeignKey("op_operational_attachments.id"))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_json: Mapped[dict] = mapped_column(JSON_TYPE)


class SourceConflict(Authored, TradeBase):
    __tablename__ = "regulation_source_conflicts"
    source_ids: Mapped[list] = mapped_column(JSON_TYPE)
    issue: Mapped[str] = mapped_column(Text)
    scope_json: Mapped[dict] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    resolution_json: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Pack(Authored, TradeBase):
    __tablename__ = "regulation_rule_pack_revisions"
    __table_args__ = (
        UniqueConstraint("family_code", "version", "environment"),
        Index(
            "ix_pack_effective", "family_code", "environment", "effective_from", "effective_until"
        ),
    )
    family_code: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    environment: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    input_schema_version: Mapped[str] = mapped_column(String(50))
    rule_schema_version: Mapped[str] = mapped_column(String(50))
    supported_scope_json: Mapped[dict] = mapped_column(JSON_TYPE)
    excluded_scope_json: Mapped[dict] = mapped_column(JSON_TYPE)
    coverage_json: Mapped[dict] = mapped_column(JSON_TYPE)
    policy_json: Mapped[dict] = mapped_column(JSON_TYPE)
    source_ids: Mapped[list] = mapped_column(JSON_TYPE)
    effective_from: Mapped[datetime] = mapped_column(TS)
    effective_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    limitations_json: Mapped[list] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    test_suite_hash: Mapped[str] = mapped_column(String(64))


class Rule(Authored, TradeBase):
    __tablename__ = "regulation_rules"
    __table_args__ = (UniqueConstraint("pack_revision_id", "rule_code"),)
    pack_revision_id: Mapped[str] = mapped_column(
        ForeignKey("regulation_rule_pack_revisions.id"), index=True
    )
    rule_code: Mapped[str] = mapped_column(String(100))
    rule_version: Mapped[str] = mapped_column(String(50))
    requirement_code: Mapped[str] = mapped_column(String(100))
    rule_class: Mapped[str] = mapped_column(String(30))
    rule_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


class TestRun(Authored, TradeBase):
    __tablename__ = "regulation_pack_test_runs"
    pack_revision_id: Mapped[str] = mapped_column(
        ForeignKey("regulation_rule_pack_revisions.id"), index=True
    )
    pack_hash: Mapped[str] = mapped_column(String(64))
    suite_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    results_json: Mapped[dict] = mapped_column(JSON_TYPE)
    engine_version: Mapped[str] = mapped_column(String(50))
    completed_at: Mapped[datetime] = mapped_column(TS)


class Publication(Authored, TradeBase):
    __tablename__ = "regulation_publication_events"
    pack_revision_id: Mapped[str] = mapped_column(
        ForeignKey("regulation_rule_pack_revisions.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30))
    pack_hash: Mapped[str] = mapped_column(String(64))
    test_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("regulation_pack_test_runs.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text)


class Registry(TradeBase):
    __tablename__ = "regulation_registry_heads"
    family_code: Mapped[str] = mapped_column(String(100), primary_key=True)
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    jurisdiction_key: Mapped[str] = mapped_column(String(10), primary_key=True)
    registry_epoch: Mapped[int] = mapped_column(BigInteger, default=0)
    publication_manifest_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TS)
