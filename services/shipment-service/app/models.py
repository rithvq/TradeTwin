import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class ShipmentStatus(StrEnum):
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_TRANSIT_PORT = "AT_TRANSIT_PORT"
    PARTIALLY_UNLOADED = "PARTIALLY_UNLOADED"


class CustomsStatus(StrEnum):
    PENDING = "PENDING"
    LOADED = "LOADED"
    UAE_TRANSIT = "UAE_TRANSIT"
    UAE_IMPORT = "UAE_IMPORT"


class ShipmentEventType(StrEnum):
    ARRIVED_AT_HUB = "ARRIVED_AT_HUB"
    DELIVERED = "DELIVERED"
    CREATED = "CREATED"
    LOADED = "LOADED"
    ARRIVED_AT_TRANSIT_PORT = "ARRIVED_AT_TRANSIT_PORT"
    UNLOADED = "UNLOADED"
    TEMPORARY_STORAGE = "TEMPORARY_STORAGE"
    TRANSSHIPMENT = "TRANSSHIPMENT"
    CONTAINER_OPENED = "CONTAINER_OPENED"
    CONTAINER_RESEALED = "CONTAINER_RESEALED"
    ROUTE_CHANGED = "ROUTE_CHANGED"


json_payload = JSON().with_variant(JSONB, "postgresql")


class GraphSyncTask(Base):
    __tablename__ = "shipment_graph_sync_tasks"
    shipment_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("owner_id", "shipment_reference", name="uq_shipments_owner_reference"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_reference: Mapped[str] = mapped_column(String(80), index=True)
    exporter_country: Mapped[str] = mapped_column(String(80))
    importer_country: Mapped[str] = mapped_column(String(80))
    transport_mode: Mapped[str] = mapped_column(String(40))
    planned_departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default=ShipmentStatus.CREATED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    domestic: Mapped[dict | None] = mapped_column(json_payload, nullable=True)

    consignments: Mapped[list["Consignment"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan"
    )
    route_legs: Mapped[list["ShipmentLeg"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan"
    )
    events: Mapped[list["ShipmentEvent"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan"
    )


class Consignment(Base):
    __tablename__ = "consignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(120))
    product_description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    declared_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    country_of_origin: Mapped[str] = mapped_column(String(80))
    destination_country: Mapped[str] = mapped_column(String(80))
    proposed_hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customs_status: Mapped[str] = mapped_column(String(40), default=CustomsStatus.PENDING)
    domestic: Mapped[dict | None] = mapped_column(json_payload, nullable=True)

    shipment: Mapped[Shipment] = relationship(back_populates="consignments")
    events: Mapped[list["ShipmentEvent"]] = relationship(back_populates="consignment")


class ShipmentLeg(Base):
    __tablename__ = "shipment_legs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    origin_country: Mapped[str] = mapped_column(String(80))
    destination_country: Mapped[str] = mapped_column(String(80))
    transport_mode: Mapped[str] = mapped_column(String(40))
    carrier_name: Mapped[str] = mapped_column(String(120))
    domestic: Mapped[dict | None] = mapped_column(json_payload, nullable=True)

    shipment: Mapped[Shipment] = relationship(back_populates="route_legs")


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    consignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("consignments.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(60))
    location_country: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_metadata: Mapped[dict] = mapped_column("metadata", json_payload, default=dict)

    shipment: Mapped[Shipment] = relationship(back_populates="events")
    consignment: Mapped[Consignment | None] = relationship(back_populates="events")
