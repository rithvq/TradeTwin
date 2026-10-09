"""Structured locations and additive storage for Indian domestic movements."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import inspect, text

STATES = (
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
)


class Location(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    state: str
    city: str = Field(min_length=1, max_length=100)
    pincode: str = Field(pattern=r"^[1-9][0-9]{5}$")

    @field_validator("state")
    @classmethod
    def valid_state(cls, value):
        match = next((state for state in STATES if state.casefold() == value.casefold()), None)
        if not match:
            raise ValueError("Select an Indian state or union territory")
        return match


class DomesticPlan(BaseModel):
    origin: Location
    destination: Location
    consignor_name: str = Field(min_length=1, max_length=120)
    consignee_name: str = Field(min_length=1, max_length=120)
    movement_reason: Literal["SUPPLY", "JOB_WORK", "STOCK_TRANSFER", "OTHER"] = "SUPPLY"
    registered_consignor: bool | None = None
    ordinary_goods: bool | None = None


class DomesticConsignment(BaseModel):
    destination: Location
    # Total document value including tax; kept distinct from item declared value.
    consignment_value: float = Field(ge=0, le=999999999999.99, allow_inf_nan=False)
    eway_bill_required: bool | None = None


class DomesticLeg(BaseModel):
    origin: Location
    destination: Location
    distance_km: float = Field(gt=0, le=10000)


def migrate_domestic(engine):
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(884922)"))
        inspector = inspect(connection)
        for table in ("shipments", "consignments", "shipment_legs"):
            if inspector.has_table(table) and "domestic" not in {
                column["name"] for column in inspector.get_columns(table)
            }:
                kind = "JSONB" if engine.dialect.name == "postgresql" else "JSON"
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN domestic {kind}"))


def same_place(first, second):
    return first["state"] == second["state"] and first["pincode"] == second["pincode"]


def validate_domestic(payload):
    plan = payload.domestic
    if not plan:
        raise ValueError("Domestic shipment details are required")
    if payload.exporter_country != "India" or payload.importer_country != "India":
        raise ValueError("New shipments must remain within India")
    if payload.transport_mode != "ROAD":
        raise ValueError("The initial domestic workflow supports road transport")
    legs = sorted(payload.route_legs, key=lambda leg: leg.sequence_number)
    if not legs or not payload.consignments:
        raise ValueError("Add at least one route leg and consignment")
    previous = plan.origin.model_dump()
    destinations = []
    for sequence, leg in enumerate(legs, 1):
        if not leg.domestic or leg.sequence_number != sequence:
            raise ValueError(
                "Route legs require domestic locations and consecutive sequence numbers"
            )
        if (
            leg.origin_country != "India"
            or leg.destination_country != "India"
            or leg.transport_mode != "ROAD"
        ):
            raise ValueError("Every route leg must be a domestic road movement")
        if not same_place(previous, leg.domestic.origin.model_dump()):
            raise ValueError("Route legs must connect from the shipment origin")
        previous = leg.domestic.destination.model_dump()
        destinations.append(previous)
    if not same_place(previous, plan.destination.model_dump()):
        raise ValueError("The final route stop must match the shipment destination")
    for item in payload.consignments:
        if item.currency != "INR" or item.destination_country != "India" or not item.domestic:
            raise ValueError("Consignments require INR values and an Indian delivery location")
        if not any(
            same_place(item.domestic.destination.model_dump(), stop) for stop in destinations
        ):
            raise ValueError("Every consignment delivery location must occur on the route")
