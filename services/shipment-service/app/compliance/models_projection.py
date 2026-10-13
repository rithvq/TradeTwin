"""Immutable delivered movement projection; the operational event remains authoritative."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, Authored, TradeBase


class MovementProjection(Authored, TradeBase):
    __tablename__ = "compliance_movement_projections"
    movement_event_id: Mapped[str] = mapped_column(ForeignKey("op_shipment_events.id"), unique=True)
    authorisation_id: Mapped[str] = mapped_column(ForeignKey("dispatch_authorizations.id"))
    projection_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))
