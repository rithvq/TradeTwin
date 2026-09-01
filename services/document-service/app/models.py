import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentType(StrEnum):
    COMMERCIAL_INVOICE = "commercial_invoice"
    PACKING_LIST = "packing_list"
    CERTIFICATE_OF_ORIGIN = "certificate_of_origin"
    SAFETY_CERTIFICATE = "safety_certificate"
    TRANSIT_DECLARATION = "transit_declaration"


class VerificationStatus(StrEnum):
    UPLOADED = "UPLOADED"
    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class EvidenceType(StrEnum):
    DOCUMENT_SUPPORTS_RULE = "DOCUMENT_SUPPORTS_RULE"
    DOCUMENT_MISSING = "DOCUMENT_MISSING"
    EVENT_TRIGGERED_RULE = "EVENT_TRIGGERED_RULE"


json_payload = JSON().with_variant(JSONB, "postgresql")


class TradeDocument(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    consignment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    shipment_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    bucket: Mapped[str] = mapped_column(String(120))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    jurisdiction: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    verification_status: Mapped[str] = mapped_column(
        String(40), default=VerificationStatus.UPLOADED, index=True
    )
    extracted_fields: Mapped[dict] = mapped_column(json_payload, default=dict)
    extracted_text_preview: Mapped[str] = mapped_column(Text, default="")
    document_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evidence_records: Mapped[list["EvidenceRecord"]] = relationship(back_populates="document")


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(String(36), index=True)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    consignment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    rule_title: Mapped[str] = mapped_column(String(255))
    regulation_version: Mapped[str] = mapped_column(String(80))
    regulation_source_url: Mapped[str] = mapped_column(String(512))
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True, index=True
    )
    shipment_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    jurisdiction: Mapped[str] = mapped_column(String(80), index=True)
    procedure_type: Mapped[str] = mapped_column(String(80), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    document: Mapped[TradeDocument | None] = relationship(back_populates="evidence_records")
