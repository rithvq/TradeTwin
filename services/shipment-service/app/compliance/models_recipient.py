from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, Snapshot, TradeBase


class RecipientConfirmation(Snapshot, TradeBase):
    __tablename__ = "compliance_recipient_confirmations"
    accepted_trade_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    confirmation_json: Mapped[dict] = mapped_column(JSON_TYPE)
