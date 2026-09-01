import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


json_payload = JSON().with_variant(JSONB, "postgresql")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    model_version: Mapped[str] = mapped_column(String(40), default="synthetic-demo-v1")
    inspection_probability: Mapped[float] = mapped_column(Float)
    rejection_probability: Mapped[float] = mapped_column(Float)
    expected_clearance_delay_hours: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(40), index=True)
    warning: Mapped[str] = mapped_column(String(160))
    features: Mapped[dict] = mapped_column(json_payload)
    risk_factors: Mapped[list] = mapped_column(json_payload)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
