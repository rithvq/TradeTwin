import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from tradetwin_security import ProfileMiddleware, migrate_ownership

from app.audit import write_audit_log
from app.auth import Principal, get_current_principal, require_role
from app.config import settings
from app.consistency import check_consistency, highest_value_question, question_catalog
from app.database import Base, engine, get_db
from app.document_client import (
    create_evidence_records,
    get_evidence_records,
    get_uploaded_documents,
    merge_documents,
)
from app.evaluator import evaluate_compliance
from app.jobs import ComplianceJobStore
from app.models import AuditLog, ComplianceAssessment, QuestionAnswer
from app.optimizer import optimize_routes
from app.regulations import (
    RegulationNotFound,
    analyze_regulation_impact,
    create_regulation_version,
    load_rules_with_published,
    publish_regulation_version,
)
from app.regulatory_sources import router as regulatory_sources_router
from app.reports import build_html_report, build_pdf_report
from app.schemas import (
    AuditLogRead,
    ComplianceAssessmentRead,
    ComplianceAssessmentResult,
    ComplianceEvaluationRequest,
    ComplianceRule,
    ConsistencyCheckRead,
    ConsistencyCheckRequest,
    DemoScenarioRead,
    ErrorResponse,
    ImpactAnalysisRead,
    ImpactAnalysisRequest,
    InformationGainQuestionRead,
    PrincipalRead,
    QuestionAnswerRead,
    QuestionAnswerRequest,
    RegulationCreateRequest,
    RegulationPublishRead,
    RegulationRead,
    ReportFormat,
    RouteOptimizationRead,
    RouteOptimizationRequest,
    UploadedDocumentMetadata,
)
from app.shipment_client import get_shipment_context
from app.state_relations import router as state_relations_router

SERVICE_NAME = "compliance-service"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    migrate_ownership(engine, Base.metadata)
    Base.metadata.create_all(bind=engine)
    app.state.job_store = ComplianceJobStore()
    yield


app = FastAPI(
    title="TradeTwin Compliance Service",
    version="0.7.0",
    description=(
        "Deterministic compliance, evidence-backed reports, route optimization, "
        "regulation impact analysis, demo auth/RBAC, and audit logs."
    ),
    openapi_tags=[
        {"name": "health", "description": "Service readiness checks."},
        {"name": "auth", "description": "Demo authentication context."},
        {"name": "compliance", "description": "Rule-based assessments."},
        {"name": "consistency", "description": "Conflict checks and questions."},
        {"name": "optimizer", "description": "Deterministic route comparison."},
        {"name": "regulations", "description": "Regulation version management."},
        {"name": "reports", "description": "HTML and PDF compliance reports."},
        {"name": "audit", "description": "Immutable-style audit trail reads."},
        {"name": "demo", "description": "Seeded project evaluation scenarios."},
    ],
    lifespan=lifespan,
)

app.add_middleware(ProfileMiddleware)
app.include_router(regulatory_sources_router)
app.include_router(state_relations_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="HTTP_ERROR",
            detail=exc.detail,
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="VALIDATION_ERROR",
            detail=jsonable_encoder(exc.errors(), custom_encoder={ValueError: str}),
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception):
    del exc
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="INTERNAL_SERVER_ERROR",
            detail="An unexpected server error occurred.",
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(mode="json"),
    )


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready", tags=["health"])
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        store = app.state.job_store
        if store._redis is not None:
            store._redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Compliance dependencies unavailable") from exc
    return {"status": "ok", "service": SERVICE_NAME}


def get_job_store() -> ComplianceJobStore:
    return app.state.job_store


@app.exception_handler(RegulationNotFound)
def regulation_not_found_handler(request: Request, exc: RegulationNotFound):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            error="NOT_FOUND",
            detail=f"Regulation not found: {exc.regulation_id}",
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(mode="json"),
    )


@app.get("/auth/me", response_model=PrincipalRead, tags=["auth"])
def read_current_principal(
    principal: Principal = Depends(get_current_principal),
):
    return PrincipalRead(actor_id=principal.actor_id, role=principal.role)


@app.post(
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


@app.post(
    "/optimizer/route-options/{shipment_id}",
    response_model=RouteOptimizationRead,
    tags=["optimizer"],
)
def optimize_shipment_route(
    shipment_id: str,
    payload: RouteOptimizationRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("viewer")),
):
    shipment, events = get_shipment_context(shipment_id)
    requested_documents = payload.uploaded_documents if payload is not None else []
    uploaded_documents = merge_documents(
        requested_documents,
        get_uploaded_documents(shipment_id),
    )
    result = optimize_routes(
        shipment,
        events,
        uploaded_documents,
        rules=load_rules_with_published(db),
        answers=get_answer_map(db, shipment_id),
    )
    write_audit_log(
        db,
        principal,
        "ROUTE_OPTIONS_GENERATED",
        "shipment",
        shipment_id,
    )
    return result


@app.post(
    "/regulations",
    response_model=RegulationRead,
    status_code=201,
    tags=["regulations"],
)
def create_regulation(
    payload: RegulationCreateRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    regulation = create_regulation_version(db, payload)
    write_audit_log(
        db,
        principal,
        "REGULATION_VERSION_CREATED",
        "regulation",
        regulation.id,
        details={"rule_id": regulation.rule.rule_id, "version": regulation.rule.version},
    )
    return regulation


@app.get("/regulations/rules", response_model=list[ComplianceRule], tags=["regulations"])
def read_regulation_rules(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("viewer")),
):
    return load_rules_with_published(db)


@app.post(
    "/regulations/{regulation_id}/publish-version",
    response_model=RegulationPublishRead,
    tags=["regulations"],
)
def publish_regulation(
    regulation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    result = publish_regulation_version(db, regulation_id)
    write_audit_log(
        db,
        principal,
        "REGULATION_VERSION_PUBLISHED",
        "regulation",
        regulation_id,
        details={
            "rule_id": result.regulation.rule.rule_id,
            "version": result.regulation.rule.version,
        },
    )
    return result


@app.post(
    "/regulations/impact-analysis",
    response_model=ImpactAnalysisRead,
    tags=["regulations"],
)
def regulation_impact_analysis(
    payload: ImpactAnalysisRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    result = analyze_regulation_impact(db, payload or ImpactAnalysisRequest())
    write_audit_log(
        db,
        principal,
        "REGULATION_IMPACT_ANALYZED",
        "regulation",
        None,
        details={"impacted_shipments": len(result.impacted_shipments)},
    )
    return result


@app.get("/reports/compliance/{shipment_id}", tags=["reports"])
def export_compliance_report(
    shipment_id: str,
    report_format: ReportFormat = Query(ReportFormat.HTML, alias="format"),
    db: Session = Depends(get_db),
    job_store: ComplianceJobStore = Depends(get_job_store),
    principal: Principal = Depends(require_role("viewer")),
):
    shipment, events = get_shipment_context(shipment_id)
    documents = get_uploaded_documents(shipment_id)
    latest = get_latest_assessment_model(db, shipment_id)
    assessment = (
        to_assessment_read(latest)
        if latest is not None
        else create_assessment(shipment_id, [], db, job_store, principal)
    )
    route_options = optimize_routes(
        shipment,
        events,
        documents,
        rules=load_rules_with_published(db),
    )
    evidence = get_evidence_records(assessment.id)
    write_audit_log(
        db,
        principal,
        "COMPLIANCE_REPORT_EXPORTED",
        "shipment",
        shipment_id,
        details={"assessment_id": assessment.id, "format": report_format},
    )

    if report_format == ReportFormat.PDF:
        pdf_bytes = build_pdf_report(shipment, assessment, evidence, route_options)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="tradetwin-{shipment_id}-report.pdf"'
                )
            },
        )

    return HTMLResponse(
        build_html_report(shipment, assessment, evidence, route_options),
        headers={
            "Content-Disposition": (f'attachment; filename="tradetwin-{shipment_id}-report.html"')
        },
    )


@app.get("/audit-logs", response_model=list[AuditLogRead], tags=["audit"])
def get_audit_logs(
    shipment_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    del principal
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if shipment_id:
        query = query.filter(AuditLog.resource_id == shipment_id)
    return query.limit(limit).all()


@app.get("/demo/scenarios", response_model=list[DemoScenarioRead], tags=["demo"])
def get_demo_scenarios():
    return [
        DemoScenarioRead(
            scenario_id="domestic-chennai-bengaluru-pune",
            title="Chennai to Bengaluru to Pune domestic deliveries",
            summary=(
                "Cotton shirts continue to Pune while a second consignment is delivered "
                "in Bengaluru. Document requirements differ by consignment value."
            ),
            shipment_reference="TT-DEMO-TN-KA-MH",
            route=["Chennai, Tamil Nadu", "Bengaluru, Karnataka", "Pune, Maharashtra"],
            consignments=[
                "Cotton shirts: Chennai to Pune",
                "Stationery: Chennai to Bengaluru",
            ],
            walkthrough_steps=[
                "Create shipment",
                "Add two consignments",
                "Upload or provide demo documents",
                "Record Bengaluru delivery event",
                "Run compliance evaluation",
                "Show independent delivery and document-readiness results",
                "Publish demo interstate packing-list policy",
                "Show affected shipment",
                "Compare alternate route",
                "Export evidence-grounded report",
            ],
        )
    ]


@app.post(
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


@app.get(
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


@app.post(
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


@app.get(
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
