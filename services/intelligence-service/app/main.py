from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.hs_classifier import classify_hs_code
from app.llm_gateway import get_gateway
from app.models import RiskAssessment
from app.risk_model import score_shipment
from app.schemas import (
    HSClassificationRequest,
    HSClassificationResponse,
    RiskAssessmentRead,
)
from app.shipment_client import get_shipment_context

SERVICE_NAME = settings.service_name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="TradeTwin Intelligence Service", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/intelligence/hs-classify", response_model=HSClassificationResponse)
def hs_classify(payload: HSClassificationRequest):
    return classify_hs_code(payload, get_gateway())


@app.post("/intelligence/risk-score/{shipment_id}", response_model=RiskAssessmentRead)
def risk_score(shipment_id: str, db: Session = Depends(get_db)):
    shipment, events = get_shipment_context(shipment_id)
    score = score_shipment(shipment, events)
    assessment = RiskAssessment(
        shipment_id=shipment_id,
        model_version=score["model_version"],
        inspection_probability=score["inspection_probability"],
        rejection_probability=score["rejection_probability"],
        expected_clearance_delay_hours=score["expected_clearance_delay_hours"],
        risk_level=score["risk_level"],
        warning=score["warning"],
        features=score["features"],
        risk_factors=score["risk_factors"],
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


@app.get("/shipments/{shipment_id}/risk-assessment", response_model=RiskAssessmentRead)
def get_risk_assessment(shipment_id: str, db: Session = Depends(get_db)):
    assessment = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.shipment_id == shipment_id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk assessment not found",
        )
    return assessment
