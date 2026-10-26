from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.freight.schemas import Timed
from app.trades.schemas import Schema


class Truck(Schema):
    height_m: Decimal = Field(gt=0, le=10)
    width_m: Decimal = Field(gt=0, le=6)
    length_m: Decimal = Field(gt=0, le=50)
    tare_kg: Decimal = Field(gt=0, le=200000)
    axle_load_kg: Decimal = Field(gt=0, le=100000)
    maximum_loaded_kg: Decimal | None = Field(default=None, gt=0, le=300000)


class Weights(Schema):
    distance: int = Field(default=2000, ge=0, le=10000)
    duration: int = Field(default=3000, ge=0, le=10000)
    road_weather_exposure: int = Field(default=3000, ge=0, le=10000)
    state_transit_history: int = Field(default=1000, ge=0, le=10000)
    toll_exposure: int = Field(default=1000, ge=0, le=10000)

    @model_validator(mode="after")
    def total(self):
        if sum(self.model_dump().values()) != 10000:
            raise ValueError("Comparison weights must total 10000 basis points (100%).")
        return self


class StudyInput(Timed):
    source_mode: Literal["LIVE", "RETAINED"] = "LIVE"
    departure_at: datetime
    truck: Truck | None = None
    dataset_revision_id: UUID | None = None
    weights: Weights = Field(default_factory=Weights)
    include_weather: bool = True
    planned_stop_seconds: int = Field(default=0, ge=0, le=604800)
    fuel_price_per_litre_minor: int | None = Field(default=None, gt=0, le=100000)
    fuel_km_per_litre: Decimal | None = Field(default=None, gt=0, le=30)

    @model_validator(mode="after")
    def fuel(self):
        if (self.fuel_price_per_litre_minor is None) != (self.fuel_km_per_litre is None):
            raise ValueError("Provide both fuel price and truck efficiency, or neither.")
        if self.source_mode == "RETAINED" and not self.dataset_revision_id:
            raise ValueError("Select a retained dataset for a retained comparison.")
        if self.source_mode == "LIVE" and self.dataset_revision_id:
            raise ValueError("Live comparisons cannot use a retained-dataset fallback.")
        return self
