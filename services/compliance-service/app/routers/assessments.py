from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.assessment_repository import to_assessment_read
from app.assessments import create_assessment
from app.auth import Principal, require_role
from app.database import get_db
from app.dependencies import get_job_store
from app.jobs import ComplianceJobStore
from app.models import ComplianceAssessment
from app.schemas import (
    ComplianceAssessmentRead,
    ComplianceEvaluationRequest,
)

router = APIRouter()


@router.post(
    "/compliance/evaluate/{shipment_id}",
    response_model=ComplianceAssessmentRead,
    tags=["compliance"],
)
def evaluate_shipment(
    shipment_id: str,
    payload: ComplianceEvaluationRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    job_store: ComplianceJobStore = Depends(get_job_store),
    principal: Principal = Depends(require_role("operator")),
):
    requested_documents = payload.uploaded_documents if payload is not None else []
    return create_assessment(shipment_id, requested_documents, db, job_store, principal)


@router.get(
    "/compliance/assessments/{shipment_id}",
    response_model=list[ComplianceAssessmentRead],
    tags=["compliance"],
)
def get_assessments(
    shipment_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("viewer")),
):
    del principal
    assessments = (
        db.query(ComplianceAssessment)
        .filter(ComplianceAssessment.shipment_id == shipment_id)
        .order_by(ComplianceAssessment.created_at.desc())
        .all()
    )
    return [to_assessment_read(assessment) for assessment in assessments]
