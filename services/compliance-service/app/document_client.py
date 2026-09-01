import logging
from typing import Any

import httpx

from app.config import settings
from app.schemas import ComplianceAssessmentResult, UploadedDocumentMetadata

logger = logging.getLogger(__name__)


def get_uploaded_documents(shipment_id: str) -> list[UploadedDocumentMetadata]:
    if not settings.document_service_enabled:
        return []

    try:
        response = httpx.get(
            f"{settings.document_service_url}/shipments/{shipment_id}/documents",
            timeout=5,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Could not load documents for shipment %s: %s", shipment_id, exc)
        return []

    return [to_uploaded_document(document) for document in response.json()]


def create_evidence_records(
    assessment_id: str,
    result: ComplianceAssessmentResult,
    uploaded_documents: list[UploadedDocumentMetadata],
) -> None:
    if not settings.document_service_enabled:
        return

    records = build_evidence_records(result, uploaded_documents)
    if not records:
        return

    try:
        response = httpx.post(
            f"{settings.document_service_url}/assessments/{assessment_id}/evidence",
            json={"records": records},
            timeout=5,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Could not create evidence for assessment %s: %s", assessment_id, exc)


def get_evidence_records(assessment_id: str) -> list[dict[str, Any]]:
    if not settings.document_service_enabled:
        return []

    try:
        response = httpx.get(
            f"{settings.document_service_url}/assessments/{assessment_id}/evidence",
            timeout=5,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Could not load evidence for assessment %s: %s", assessment_id, exc)
        return []

    return response.json()


def merge_documents(
    requested_documents: list[UploadedDocumentMetadata],
    stored_documents: list[UploadedDocumentMetadata],
) -> list[UploadedDocumentMetadata]:
    merged: dict[str, UploadedDocumentMetadata] = {}
    for document in [*requested_documents, *stored_documents]:
        merged[document.document_id] = document
    return list(merged.values())


def to_uploaded_document(document: dict[str, Any]) -> UploadedDocumentMetadata:
    return UploadedDocumentMetadata(
        document_id=document["id"],
        document_type=document["document_type"],
        filename=document.get("filename"),
        consignment_id=document.get("consignment_id"),
        shipment_event_id=document.get("shipment_event_id"),
        jurisdiction=document.get("jurisdiction"),
        metadata={
            "source": "document-service",
            "verification_status": document.get("verification_status"),
            "document_number": document.get("document_number"),
            "document_date": document.get("document_date"),
            "extracted_fields": document.get("extracted_fields") or {},
        },
    )


def build_evidence_records(
    result: ComplianceAssessmentResult,
    uploaded_documents: list[UploadedDocumentMetadata],
) -> list[dict[str, Any]]:
    documents_by_id = {document.document_id: document for document in uploaded_documents}
    records: list[dict[str, Any]] = []

    for consignment_result in result.consignment_results:
        for rule in consignment_result.applicable_rules:
            for document_id in rule.supporting_document_ids:
                document = documents_by_id.get(document_id)
                if not should_create_document_evidence(document):
                    continue
                records.append(
                    {
                        "shipment_id": result.shipment_id,
                        "consignment_id": consignment_result.consignment_id,
                        "rule_id": rule.rule_id,
                        "rule_title": rule.title,
                        "regulation_version": rule.version,
                        "regulation_source_url": rule.source_url,
                        "document_id": document_id,
                        "shipment_event_id": (
                            document.shipment_event_id
                            if document and document.shipment_event_id
                            else rule.shipment_event_id
                        ),
                        "jurisdiction": rule.jurisdiction,
                        "procedure_type": rule.procedure_type,
                        "evidence_type": "DOCUMENT_SUPPORTS_RULE",
                        "explanation": (
                            f"{document_label(document, document_id)} satisfied "
                            f"{rule.rule_id} for {consignment_result.product_name}."
                        ),
                    }
                )

            for missing_document in rule.missing_documents:
                records.append(
                    {
                        "shipment_id": result.shipment_id,
                        "consignment_id": consignment_result.consignment_id,
                        "rule_id": rule.rule_id,
                        "rule_title": rule.title,
                        "regulation_version": rule.version,
                        "regulation_source_url": rule.source_url,
                        "document_id": None,
                        "shipment_event_id": rule.shipment_event_id,
                        "jurisdiction": rule.jurisdiction,
                        "procedure_type": rule.procedure_type,
                        "evidence_type": "DOCUMENT_MISSING",
                        "explanation": (
                            f"{missing_document} is still missing for "
                            f"{consignment_result.product_name}."
                        ),
                    }
                )

            if not rule.required_documents and rule.shipment_event_id:
                records.append(
                    {
                        "shipment_id": result.shipment_id,
                        "consignment_id": consignment_result.consignment_id,
                        "rule_id": rule.rule_id,
                        "rule_title": rule.title,
                        "regulation_version": rule.version,
                        "regulation_source_url": rule.source_url,
                        "document_id": None,
                        "shipment_event_id": rule.shipment_event_id,
                        "jurisdiction": rule.jurisdiction,
                        "procedure_type": rule.procedure_type,
                        "evidence_type": "EVENT_TRIGGERED_RULE",
                        "explanation": (
                            f"Shipment event {rule.shipment_event_id} triggered "
                            f"{rule.rule_id} for {consignment_result.product_name}."
                        ),
                    }
                )

    return records


def document_label(document: UploadedDocumentMetadata | None, document_id: str) -> str:
    if document is None:
        return document_id
    if document.filename:
        return document.filename
    return document.document_type


def should_create_document_evidence(document: UploadedDocumentMetadata | None) -> bool:
    if document is None:
        return False
    source = document.metadata.get("source")
    has_verification_state = document.metadata.get("verification_status") is not None
    return source in {"document-service", "document-upload-page"} or has_verification_state
