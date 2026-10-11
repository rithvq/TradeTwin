from sqlalchemy.orm import Session

from app.assessment_repository import get_answer_map, to_assessment_read
from app.audit import write_audit_log
from app.auth import Principal
from app.document_client import (
    create_evidence_records,
    get_uploaded_documents,
    merge_documents,
)
from app.evaluator import evaluate_compliance
from app.jobs import ComplianceJobStore
from app.models import ComplianceAssessment
from app.regulations import (
    load_rules_with_published,
)
from app.schemas import (
    ComplianceAssessmentRead,
    UploadedDocumentMetadata,
)
from app.shipment_client import get_shipment_context


def create_assessment(
    shipment_id: str,
    requested_documents: list[UploadedDocumentMetadata],
    db: Session,
    job_store: ComplianceJobStore,
    principal: Principal | None = None,
) -> ComplianceAssessmentRead:
    job_id = job_store.start(shipment_id)
    try:
        shipment, events = get_shipment_context(shipment_id)
        uploaded_documents = merge_documents(
            requested_documents,
            get_uploaded_documents(shipment_id),
        )
        result = evaluate_compliance(
            shipment,
            events,
            uploaded_documents,
            rules=load_rules_with_published(db),
            answers=get_answer_map(db, shipment_id),
        )
        assessment = ComplianceAssessment(
            shipment_id=shipment_id,
            job_id=job_id,
            status=result.status,
            result_payload=result.model_dump(mode="json"),
        )
        db.add(assessment)
        db.flush()
        create_evidence_records(assessment.id, result, uploaded_documents)
        db.commit()
        db.refresh(assessment)
        job_store.complete(job_id, assessment.id)
        if principal is not None:
            write_audit_log(
                db,
                principal,
                "COMPLIANCE_ASSESSMENT_CREATED",
                "shipment",
                shipment_id,
                details={"assessment_id": assessment.id, "status": result.status},
            )
        return to_assessment_read(assessment)
    except Exception as exc:
        db.rollback()
        job_store.fail(job_id, str(exc))
        raise
