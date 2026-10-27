from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.trades.models import JSON_TYPE, Mutable, Record, TradeBase


class Launch(Mutable, TradeBase):
    __tablename__ = "demo_app_launches"
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"), index=True)
    control_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    trade_id: Mapped[str | None] = mapped_column(ForeignKey("trades.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    manifest_version: Mapped[str] = mapped_column(String(40))
    fixture_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    next_step: Mapped[int] = mapped_column(default=0)
    active_command_id: Mapped[str | None] = mapped_column(String(36))
    predecessor_id: Mapped[str | None] = mapped_column(ForeignKey("demo_app_launches.id"))


class Command(Record, TradeBase):
    __tablename__ = "demo_app_commands"
    launch_id: Mapped[str] = mapped_column(ForeignKey(Launch.id), index=True)
    step_code: Mapped[str] = mapped_column(String(60))
    job_id: Mapped[str] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    receipt_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error_code: Mapped[str | None] = mapped_column(String(80))


TABLES = [Launch, Command]
