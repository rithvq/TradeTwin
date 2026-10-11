from sqlalchemy.orm import Session

from app.models import ComplianceAssessment, QuestionAnswer
from app.schemas import ComplianceAssessmentRead, ComplianceAssessmentResult


def get_answer_map(db: Session, shipment_id: str) -> dict[str, str]:
    answers = (
        db.query(QuestionAnswer)
        .filter(QuestionAnswer.shipment_id == shipment_id)
        .order_by(QuestionAnswer.created_at.desc())
        .all()
    )
    answer_map: dict[str, str] = {}
    for answer in answers:
        answer_map.setdefault(answer.attribute_key, answer.answer)
    return answer_map


def get_latest_assessment_model(
    db: Session,
    shipment_id: str,
) -> ComplianceAssessment | None:
    return (
        db.query(ComplianceAssessment)
        .filter(ComplianceAssessment.shipment_id == shipment_id)
        .order_by(ComplianceAssessment.created_at.desc())
        .first()
    )


def to_assessment_read(assessment: ComplianceAssessment) -> ComplianceAssessmentRead:
    return ComplianceAssessmentRead(
        id=assessment.id,
        shipment_id=assessment.shipment_id,
        job_id=assessment.job_id,
        status=assessment.status,
        created_at=assessment.created_at,
        result=ComplianceAssessmentResult.model_validate(assessment.result_payload),
    )
