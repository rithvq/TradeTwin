from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import Base, engine, get_db
from app.extraction import extract_document_fields, parse_date
from app.models import (
    DocumentType,
    EvidenceRecord,
    TradeDocument,
    VerificationStatus,
    new_id,
    utc_now,
)
from app.schemas import (
    EvidenceBatchCreate,
    EvidenceRecordRead,
    ExtractedDocumentRead,
    TradeDocumentRead,
)
from app.storage import ObjectStorage

SERVICE_NAME = settings.service_name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    storage_client = ObjectStorage()
    storage_client.ensure_bucket()
    app.state.storage = storage_client
    yield


app = FastAPI(title="TradeTwin Document Service", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


def get_storage() -> ObjectStorage:
    return app.state.storage


@app.post(
    "/shipments/{shipment_id}/documents",
    response_model=TradeDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    shipment_id: str,
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    consignment_id: str | None = Form(default=None),
    shipment_event_id: str | None = Form(default=None),
    jurisdiction: str | None = Form(default=None),
    db: Session = Depends(get_db),
    storage_client: ObjectStorage = Depends(get_storage),
):
    document_id = new_id()
    object_key, size_bytes = await storage_client.put_upload(shipment_id, document_id, file)
    document = TradeDocument(
        id=document_id,
        shipment_id=shipment_id,
        consignment_id=empty_to_none(consignment_id),
        shipment_event_id=empty_to_none(shipment_event_id),
        document_type=document_type.value,
        filename=file.filename or "document.bin",
        content_type=file.content_type or "application/octet-stream",
        bucket=storage_client.bucket,
        object_key=object_key,
        size_bytes=size_bytes,
        jurisdiction=empty_to_none(jurisdiction),
        verification_status=VerificationStatus.UPLOADED,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@app.post("/documents/{document_id}/extract", response_model=ExtractedDocumentRead)
def extract_document(
    document_id: str,
    db: Session = Depends(get_db),
    storage_client: ObjectStorage = Depends(get_storage),
):
    document = get_document_or_404(db, document_id)
    try:
        content = storage_client.get_bytes(document.object_key)
        extracted_text, extracted_fields = extract_document_fields(
            content,
            document.filename,
            document.content_type,
        )
    except Exception as exc:
        document.verification_status = VerificationStatus.FAILED
        document.extracted_fields = {"error": str(exc)}
        document.extracted_at = utc_now()
        db.commit()
        db.refresh(document)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Document extraction failed",
        ) from exc

    document.extracted_fields = extracted_fields
    document.extracted_text_preview = extracted_text[:1200]
    document.document_number = extracted_fields.get("document_number")
    document.document_date = extract_date_field(extracted_fields.get("document_date"))
    document.verification_status = (
        VerificationStatus.EXTRACTED if extracted_fields else VerificationStatus.NEEDS_REVIEW
    )
    document.extracted_at = utc_now()
    db.commit()
    db.refresh(document)
    return document


@app.get("/documents/{document_id}", response_model=TradeDocumentRead)
def get_document(document_id: str, db: Session = Depends(get_db)):
    return get_document_or_404(db, document_id)


@app.get("/shipments/{shipment_id}/documents", response_model=list[TradeDocumentRead])
def list_documents_for_shipment(shipment_id: str, db: Session = Depends(get_db)):
    return (
        db.query(TradeDocument)
        .filter(TradeDocument.shipment_id == shipment_id)
        .order_by(TradeDocument.uploaded_at.desc())
        .all()
    )


@app.post(
    "/assessments/{assessment_id}/evidence",
    response_model=list[EvidenceRecordRead],
    status_code=status.HTTP_201_CREATED,
)
def create_evidence_records(
    assessment_id: str,
    payload: EvidenceBatchCreate,
    db: Session = Depends(get_db),
):
    db.query(EvidenceRecord).filter(EvidenceRecord.assessment_id == assessment_id).delete()
    records = [
        EvidenceRecord(assessment_id=assessment_id, **record.model_dump(mode="json"))
        for record in payload.records
    ]
    db.add_all(records)
    db.commit()
    return (
        db.query(EvidenceRecord)
        .options(joinedload(EvidenceRecord.document))
        .filter(EvidenceRecord.assessment_id == assessment_id)
        .order_by(EvidenceRecord.created_at.asc())
        .all()
    )


@app.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceRecordRead])
def get_evidence_records(assessment_id: str, db: Session = Depends(get_db)):
    return (
        db.query(EvidenceRecord)
        .options(joinedload(EvidenceRecord.document))
        .filter(EvidenceRecord.assessment_id == assessment_id)
        .order_by(EvidenceRecord.created_at.asc())
        .all()
    )


def get_document_or_404(db: Session, document_id: str) -> TradeDocument:
    document = db.get(TradeDocument, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return document


def empty_to_none(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value


def extract_date_field(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    return parse_date(value)
