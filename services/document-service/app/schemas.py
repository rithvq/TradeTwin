from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import DocumentType, EvidenceType, VerificationStatus


class TradeDocumentRead(BaseModel):
    id: str
    shipment_id: str
    consignment_id: str | None
    shipment_event_id: str | None
    document_type: str
    filename: str
    content_type: str
    size_bytes: int
    jurisdiction: str | None
    verification_status: str
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    extracted_text_preview: str
    document_number: str | None
    document_date: date | None
    uploaded_at: datetime
    extracted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ExtractedDocumentRead(TradeDocumentRead):
    pass


class EvidenceRecordCreate(BaseModel):
    shipment_id: str
    consignment_id: str | None = None
    rule_id: str
    rule_title: str
    regulation_version: str
    regulation_source_url: str
    document_id: str | None = None
    shipment_event_id: str | None = None
    jurisdiction: str
    procedure_type: str
    evidence_type: EvidenceType
    explanation: str


class EvidenceBatchCreate(BaseModel):
    records: list[EvidenceRecordCreate] = Field(default_factory=list)


class EvidenceRecordRead(BaseModel):
    id: str
    assessment_id: str
    shipment_id: str
    consignment_id: str | None
    rule_id: str
    rule_title: str
    regulation_version: str
    regulation_source_url: str
    document_id: str | None
    shipment_event_id: str | None
    jurisdiction: str
    procedure_type: str
    evidence_type: str
    explanation: str
    created_at: datetime
    document: TradeDocumentRead | None = None

    model_config = ConfigDict(from_attributes=True)


DOCUMENT_TYPE_VALUES = [document_type.value for document_type in DocumentType]
VERIFICATION_STATUS_VALUES = [status.value for status in VerificationStatus]
