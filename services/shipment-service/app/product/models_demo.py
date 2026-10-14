"""Bounded guided demonstration records. Business records remain in their owning modules."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.freight.models import Snapshot
from app.trades.models import JSON_TYPE, Mutable, TradeBase

TS = DateTime(timezone=True)


class Scenario(Snapshot, TradeBase):
    __tablename__ = "demo_scenario_revisions"
    __table_args__ = (UniqueConstraint("scenario_code", "version"),)
    scenario_code: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    scenario_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Workspace(Mutable, TradeBase):
    __tablename__ = "demo_workspaces"
    scenario_revision_id: Mapped[str] = mapped_column(ForeignKey(Scenario.id))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    owner_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    trade_id: Mapped[str | None] = mapped_column(ForeignKey("trades.id"), unique=True)
    predecessor_workspace_id: Mapped[str | None] = mapped_column(ForeignKey("demo_workspaces.id"))
    state: Mapped[str] = mapped_column(String(20), default="OPEN")


class Clock(TradeBase):
    __tablename__ = "demo_clock_heads"
    workspace_id: Mapped[str] = mapped_column(ForeignKey(Workspace.id), primary_key=True)
    virtual_as_of: Mapped[datetime] = mapped_column(TS)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class ClockEvent(Snapshot, TradeBase):
    __tablename__ = "demo_clock_events"
    workspace_id: Mapped[str] = mapped_column(ForeignKey(Workspace.id))
    event_json: Mapped[dict] = mapped_column(JSON_TYPE)


class DemoRun(Mutable, TradeBase):
    __tablename__ = "demo_runs"
    workspace_id: Mapped[str] = mapped_column(ForeignKey(Workspace.id))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    current_step_code: Mapped[str | None] = mapped_column(String(100))


class StepReceipt(Snapshot, TradeBase):
    __tablename__ = "demo_step_receipts"
    run_id: Mapped[str] = mapped_column(ForeignKey(DemoRun.id))
    step_code: Mapped[str] = mapped_column(String(100))
    principal_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    receipt_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Checkpoint(Snapshot, TradeBase):
    __tablename__ = "demo_checkpoint_results"
    step_receipt_id: Mapped[str] = mapped_column(ForeignKey(StepReceipt.id))
    assertion_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Measurement(Snapshot, TradeBase):
    __tablename__ = "demo_measurement_results"
    run_id: Mapped[str] = mapped_column(ForeignKey(DemoRun.id))
    measurement_json: Mapped[dict] = mapped_column(JSON_TYPE)


TABLES = [Scenario, Workspace, Clock, ClockEvent, DemoRun, StepReceipt, Checkpoint, Measurement]
IMMUTABLE_TABLES = [m.__tablename__ for m in TABLES if m not in {Workspace, Clock, DemoRun}]
