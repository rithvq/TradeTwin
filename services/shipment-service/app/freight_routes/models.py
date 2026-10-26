from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.compliance.model_base import JSON_TYPE, ConsignmentRecord, TradeBase


class RouteStudy(ConsignmentRecord, TradeBase):
    __tablename__ = "freight_route_studies"
    organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), index=True)
    execution_mode: Mapped[str] = mapped_column(String(20))
    source_mode: Mapped[str] = mapped_column(String(20))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    job_state: Mapped[str] = mapped_column(String(30), default="QUEUED")
    input_json: Mapped[dict] = mapped_column(JSON_TYPE)
    input_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


TABLES = [RouteStudy]
