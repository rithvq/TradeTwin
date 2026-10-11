from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.assessment_repository import get_latest_assessment_model, to_assessment_read
from app.assessments import create_assessment
from app.audit import write_audit_log
from app.auth import Principal, require_role
from app.database import get_db
from app.dependencies import get_job_store
from app.document_client import (
    get_evidence_records,
    get_uploaded_documents,
)
from app.jobs import ComplianceJobStore
from app.optimizer import optimize_routes
from app.regulations import (
    load_rules_with_published,
)
from app.reports import build_html_report, build_pdf_report
from app.schemas import (
    ReportFormat,
)
from app.shipment_client import get_shipment_context

router = APIRouter()


@router.get("/reports/compliance/{shipment_id}", tags=["reports"])
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
