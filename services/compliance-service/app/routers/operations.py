from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_principal, require_role
from app.database import get_db
from app.models import AuditLog
from app.schemas import (
    AuditLogRead,
    DemoScenarioRead,
    PrincipalRead,
)

router = APIRouter()


@router.get("/auth/me", response_model=PrincipalRead, tags=["auth"])
def read_current_principal(
    principal: Principal = Depends(get_current_principal),
):
    return PrincipalRead(actor_id=principal.actor_id, role=principal.role)


@router.get("/audit-logs", response_model=list[AuditLogRead], tags=["audit"])
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


@router.get("/demo/scenarios", response_model=list[DemoScenarioRead], tags=["demo"])
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
