from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.trades.models import JSON_TYPE, Record, TradeBase

TS = DateTime(timezone=True)


class Authored(Record):
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class ConsignmentRecord(Authored):
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)


class Snapshot(ConsignmentRecord):
    content_hash: Mapped[str] = mapped_column(String(64))


__all__ = ["Authored", "ConsignmentRecord", "JSON_TYPE", "Snapshot", "TS", "TradeBase"]
