import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


json_payload = JSON().with_variant(JSONB, "postgresql")


class ComplianceAssessment(Base):
    __tablename__ = "compliance_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    result_payload: Mapped[dict] = mapped_column("result", json_payload)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuestionAnswer(Base):
    __tablename__ = "question_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    question_id: Mapped[str] = mapped_column(String(160), index=True)
    consignment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    attribute_key: Mapped[str] = mapped_column(String(160), index=True)
    answer: Mapped[str] = mapped_column(String(255))
    answer_metadata: Mapped[dict] = mapped_column("metadata", json_payload, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegulationVersion(Base):
    __tablename__ = "regulation_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(255))
    jurisdiction: Mapped[str] = mapped_column(String(80), index=True)
    procedure_type: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    rule_payload: Mapped[dict] = mapped_column("rule", json_payload)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    details: Mapped[dict] = mapped_column(json_payload, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegulatorySourceSnapshot(Base):
    __tablename__ = "regulatory_source_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    url: Mapped[str] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(json_payload)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegulatorySourceReview(Base):
    __tablename__ = "regulatory_source_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    regulation_id: Mapped[str] = mapped_column(String(36), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(json_payload)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StateRelationRecord(Base):
    __tablename__ = "state_relation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str] = mapped_column(String(160), index=True)
    payload: Mapped[dict] = mapped_column(json_payload)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
