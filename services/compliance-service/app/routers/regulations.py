from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.audit import write_audit_log
from app.auth import Principal, require_role
from app.database import get_db
from app.regulations import (
    analyze_regulation_impact,
    create_regulation_version,
    load_rules_with_published,
    publish_regulation_version,
)
from app.schemas import (
    ComplianceRule,
    ImpactAnalysisRead,
    ImpactAnalysisRequest,
    RegulationCreateRequest,
    RegulationPublishRead,
    RegulationRead,
)

router = APIRouter()


@router.post(
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


@router.get("/regulations/rules", response_model=list[ComplianceRule], tags=["regulations"])
def read_regulation_rules(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role("viewer")),
):
    return load_rules_with_published(db)


@router.post(
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


@router.post(
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
