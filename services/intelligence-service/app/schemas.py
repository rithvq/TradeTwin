from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HSClassificationRequest(BaseModel):
    consignment_id: str | None = None
    product_name: str
    product_description: str = ""
    country_of_origin: str | None = None
    destination_country: str | None = None


class HSCodeRecommendation(BaseModel):
    hs_code: str
    title: str
    confidence: float
    human_review_required: bool
    tariff_notes: str
    matched_terms: list[str] = Field(default_factory=list)


class HSClassificationResponse(BaseModel):
    provider: str
    model: str
    confidence_threshold: float
    recommendations: list[HSCodeRecommendation]


class RiskFactor(BaseModel):
    factor: str
    impact: str
    explanation: str


class RiskAssessmentRead(BaseModel):
    id: str
    shipment_id: str
    model_version: str
    inspection_probability: float
    rejection_probability: float
    expected_clearance_delay_hours: float
    risk_level: str
    warning: str
    features: dict[str, Any]
    risk_factors: list[RiskFactor]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
