from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.assessment_repository import get_answer_map
from app.audit import write_audit_log
from app.auth import Principal, require_role
from app.database import get_db
from app.document_client import (
    get_uploaded_documents,
    merge_documents,
)
from app.optimizer import optimize_routes
from app.regulations import (
    load_rules_with_published,
)
from app.schemas import (
    RouteOptimizationRead,
    RouteOptimizationRequest,
)
from app.shipment_client import get_shipment_context

router = APIRouter()


@router.post(
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
