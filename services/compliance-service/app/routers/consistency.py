from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.assessment_repository import get_answer_map
from app.assessments import create_assessment
from app.auth import Principal, require_role
from app.consistency import check_consistency, highest_value_question, question_catalog
from app.database import get_db
from app.dependencies import get_job_store
from app.document_client import (
    get_uploaded_documents,
    merge_documents,
)
from app.jobs import ComplianceJobStore
from app.models import QuestionAnswer
from app.regulations import (
    load_rules_with_published,
)
from app.schemas import (
    ConsistencyCheckRead,
    ConsistencyCheckRequest,
    InformationGainQuestionRead,
    QuestionAnswerRead,
    QuestionAnswerRequest,
)
from app.shipment_client import get_shipment_context

router = APIRouter()


@router.post(
    "/consistency/check/{shipment_id}",
    response_model=ConsistencyCheckRead,
    tags=["consistency"],
)
def check_shipment_consistency(
    shipment_id: str,
    payload: ConsistencyCheckRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("viewer")),
):
    del principal
    shipment, events = get_shipment_context(shipment_id)
    requested_documents = payload.uploaded_documents if payload is not None else []
    uploaded_documents = merge_documents(
        requested_documents,
        get_uploaded_documents(shipment_id),
    )
    return check_consistency(
        shipment,
        events,
        uploaded_documents,
        answers=get_answer_map(db, shipment_id),
    )


@router.get(
    "/shipments/{shipment_id}/questions",
    response_model=list[InformationGainQuestionRead],
    tags=["consistency"],
)
def get_shipment_questions(
    shipment_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("viewer")),
):
    del principal
    shipment, events = get_shipment_context(shipment_id)
    uploaded_documents = get_uploaded_documents(shipment_id)
    question = highest_value_question(
        shipment,
        events,
        uploaded_documents,
        answers=get_answer_map(db, shipment_id),
        rules=load_rules_with_published(db),
    )
    return [question] if question else []


@router.post(
    "/shipments/{shipment_id}/questions/{question_id}/answer",
    response_model=QuestionAnswerRead,
    tags=["consistency"],
)
def answer_shipment_question(
    shipment_id: str,
    question_id: str,
    payload: QuestionAnswerRequest,
    db: Session = Depends(get_db),
    job_store: ComplianceJobStore = Depends(get_job_store),
    principal: Principal = Depends(require_role("operator")),
):
    shipment, events = get_shipment_context(shipment_id)
    uploaded_documents = get_uploaded_documents(shipment_id)
    question = next(
        (
            candidate
            for candidate in question_catalog(
                shipment, events, uploaded_documents, load_rules_with_published(db)
            )
            if candidate.question_id == question_id
        ),
        None,
    )
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )

    normalized_answer = payload.answer.strip().lower()
    if normalized_answer not in {option.lower() for option in question.answer_options}:
        raise HTTPException(status_code=422, detail="Choose one of the question's answer options")

    answer = QuestionAnswer(
        shipment_id=shipment_id,
        question_id=question.question_id,
        consignment_id=question.consignment_id,
        attribute_key=question.attribute_key,
        answer=normalized_answer,
        answer_metadata=payload.metadata,
    )
    db.add(answer)
    db.commit()

    assessment = create_assessment(
        shipment_id,
        payload.uploaded_documents,
        db,
        job_store,
        principal,
    )
    return QuestionAnswerRead(
        question=question,
        answer=answer.answer,
        assessment=assessment,
    )
