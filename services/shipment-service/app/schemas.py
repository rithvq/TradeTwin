from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import ShipmentEventType


class ConsignmentCreate(BaseModel):
    product_name: str
    product_description: str
    quantity: int
    declared_value: Decimal
    currency: str
    country_of_origin: str
    destination_country: str
    proposed_hs_code: str | None = None


class ConsignmentRead(ConsignmentCreate):
    id: str
    shipment_id: str
    customs_status: str

    model_config = ConfigDict(from_attributes=True)


class ShipmentLegCreate(BaseModel):
    sequence_number: int
    origin_country: str
    destination_country: str
    transport_mode: str
    carrier_name: str


class ShipmentLegRead(ShipmentLegCreate):
    id: str
    shipment_id: str

    model_config = ConfigDict(from_attributes=True)


class ShipmentEventCreate(BaseModel):
    consignment_id: str | None = None
    event_type: ShipmentEventType
    location_country: str
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShipmentEventRead(BaseModel):
    id: str
    shipment_id: str
    consignment_id: str | None
    event_type: str
    location_country: str
    occurred_at: datetime
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="event_metadata",
        serialization_alias="metadata",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ShipmentCreate(BaseModel):
    shipment_reference: str
    exporter_country: str
    importer_country: str
    transport_mode: str
    planned_departure_at: datetime
    planned_arrival_at: datetime
    consignments: list[ConsignmentCreate] = Field(default_factory=list)
    route_legs: list[ShipmentLegCreate] = Field(default_factory=list)


class ShipmentRead(BaseModel):
    id: str
    shipment_reference: str
    exporter_country: str
    importer_country: str
    transport_mode: str
    planned_departure_at: datetime
    planned_arrival_at: datetime
    status: str
    created_at: datetime
    consignments: list[ConsignmentRead] = Field(default_factory=list)
    route_legs: list[ShipmentLegRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TimelineRead(BaseModel):
    shipment_id: str
    events: list[ShipmentEventRead]


class GraphNode(BaseModel):
    id: str
    label: str
    type: str


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str


class ShipmentGraphRead(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
