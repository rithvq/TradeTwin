from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import Authored, TradeBase


class PrivateSource(Authored, TradeBase):
    __tablename__ = "compliance_private_source_documents"
    document_id: Mapped[str] = mapped_column(ForeignKey("doc_documents.id"), unique=True)
    seller_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
