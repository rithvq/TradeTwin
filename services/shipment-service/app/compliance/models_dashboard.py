"""Immutable, redacted explanations, separate from dispatch authority and private witnesses."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, Authored, TradeBase


class EvidenceChangeBaseline(Authored, TradeBase):
    __tablename__ = "compliance_evidence_change_baselines"
    __table_args__ = (UniqueConstraint("evaluation_id"),)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    summary_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


class AuthorizationWindow(Authored, TradeBase):
    __tablename__ = "dispatch_authorization_windows"
    __table_args__ = (UniqueConstraint("authorization_id"),)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("dispatch_authorizations.id"))
    summary_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


TABLES = [EvidenceChangeBaseline, AuthorizationWindow]
