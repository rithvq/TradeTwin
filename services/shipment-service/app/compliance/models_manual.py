from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, Authored, TradeBase


class ManualEvidence(Authored, TradeBase):
    __tablename__ = "compliance_manual_observed_fields"
    attestation_id: Mapped[str] = mapped_column(
        ForeignKey("doc_manual_attestations.id"), unique=True
    )
    observed_fields_json: Mapped[dict] = mapped_column(JSON_TYPE)
    supporting_attachment_ids: Mapped[list] = mapped_column(JSON_TYPE)


class ManualReview(Authored, TradeBase):
    __tablename__ = "compliance_manual_observation_reviews"
    attestation_id: Mapped[str] = mapped_column(
        ForeignKey("doc_manual_attestations.id"), index=True
    )
    decision: Mapped[str] = mapped_column(Text)
    reviewer_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    reason: Mapped[str] = mapped_column(Text)
