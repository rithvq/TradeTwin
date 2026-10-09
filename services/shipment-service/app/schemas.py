from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domestic import DomesticConsignment, DomesticLeg, DomesticPlan
from app.models import ShipmentEventType


def normalize_country(value: str) -> str:
    aliases = {
        "india": "India",
        "in": "India",
        "ind": "India",
        "uae": "UAE",
        "ae": "UAE",
        "are": "UAE",
        "united arab emirates": "UAE",
        "germany": "Germany",
        "de": "Germany",
        "deu": "Germany",
    }
    return aliases.get(value.strip().casefold(), value.strip())


class ConsignmentCreate(BaseModel):
    domestic: DomesticConsignment | None = None
    model_config = ConfigDict(str_strip_whitespace=True)
    product_name: str = Field(min_length=1, max_length=120)
    product_description: str
    quantity: int = Field(gt=0)
    declared_value: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    country_of_origin: str = Field(min_length=1, max_length=80)
    destination_country: str = Field(min_length=1, max_length=80)
    proposed_hs_code: str | None = Field(default=None, max_length=20)

    _countries = field_validator("country_of_origin", "destination_country")(normalize_country)


class ConsignmentRead(ConsignmentCreate):
    id: str
    shipment_id: str
    customs_status: str

    model_config = ConfigDict(from_attributes=True)


class ShipmentLegCreate(BaseModel):
    domestic: DomesticLeg | None = None
    sequence_number: int = Field(gt=0)
    origin_country: str
    destination_country: str
    transport_mode: str
    carrier_name: str

    _countries = field_validator("origin_country", "destination_country")(normalize_country)


class ShipmentLegRead(ShipmentLegCreate):
    id: str
    shipment_id: str

    model_config = ConfigDict(from_attributes=True)


class ShipmentEventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    consignment_id: str | None = None
    event_type: ShipmentEventType
    location_country: str = Field(min_length=1, max_length=80)
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    _countries = field_validator("location_country")(normalize_country)


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
    domestic: DomesticPlan | None = None
    model_config = ConfigDict(str_strip_whitespace=True)
    shipment_reference: str = Field(min_length=1, max_length=80)
    exporter_country: str = Field(min_length=1, max_length=80)
    importer_country: str = Field(min_length=1, max_length=80)
    transport_mode: str = Field(min_length=1, max_length=40)
    planned_departure_at: datetime
    planned_arrival_at: datetime
    consignments: list[ConsignmentCreate] = Field(default_factory=list)
    route_legs: list[ShipmentLegCreate] = Field(default_factory=list)

    _countries = field_validator("exporter_country", "importer_country")(normalize_country)

    @field_validator("planned_departure_at", "planned_arrival_at")
    @classmethod
    def normalize_date(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @model_validator(mode="after")
    def validate_plan(self):
        if self.planned_arrival_at < self.planned_departure_at:
            raise ValueError("Planned arrival must not precede departure")
        sequences = [leg.sequence_number for leg in self.route_legs]
        if len(sequences) != len(set(sequences)):
            raise ValueError("Route leg sequence numbers must be unique")
        return self


class ShipmentRead(BaseModel):
    domestic: DomesticPlan | None = None
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
