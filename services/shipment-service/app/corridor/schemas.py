"""Bounded typed commands. Derived hashes, lifecycle and author fields are server-owned."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.freight.schemas import Timed

Mode = Literal["SIMULATION", "PRODUCTION"]
Kind = Literal[
    "WEATHER_WARNING",
    "ROAD_CLOSURE",
    "TRAFFIC_RESTRICTION",
    "STRIKE_NOTICE",
    "FLOOD_REPORT",
    "CONGESTION_REPORT",
    "REOPENING_NOTICE",
    "PRICE_OBSERVATION",
    "OTHER",
]


class Reason(Timed):
    reason: str = Field(min_length=1, max_length=2000)


class Exact(Reason):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ConnectionInput(Timed):
    provider_code: Literal[
        "MANUAL_OFFICIAL",
        "CARRIER_OBSERVATION",
        "SIMULATION",
        "IMD_NOWCAST",
        "IMD_DISTRICT_WARNING",
        "SACHET_CAP",
        "LICENSED_NEWS",
    ]
    environment: Mode
    source_kind: Literal[
        "OFFICIAL_CAP",
        "OFFICIAL_WEATHER_API",
        "OFFICIAL_ADVISORY",
        "LICENSED_NEWS",
        "CARRIER_OBSERVATION",
        "SIMULATION",
    ]
    documented_endpoint_reference: str = Field(min_length=1, max_length=500)
    endpoint_contract_version: str = Field(min_length=1, max_length=50)
    approved_https_hosts: list[str] = Field(max_length=10)
    covered_state_codes: list[str] = Field(min_length=1, max_length=40)
    covered_event_kinds: list[Kind] = Field(min_length=1, max_length=10)
    mapping_revision_id: UUID | None = None
    access_approval_reference: str | None = Field(default=None, max_length=300)
    vault_secret_reference: str | None = Field(default=None, max_length=200)
    polling_interval_seconds: int = Field(default=300, ge=60, le=86400)
    maximum_item_age_seconds: int = Field(default=3600, ge=60, le=604800)
    request_timeout_seconds: int = Field(default=15, ge=1, le=30)
    retention_policy: Literal["PERMITTED_ARCHIVE", "UNTIL_DATE", "METADATA_ONLY"]
    retention_until: datetime | None = None
    source_item_storage_allowed: bool
    export_allowed: bool = False
    article_storage_allowed: bool = False
    attribution_text: str = Field(min_length=1, max_length=500)


class ConnectionStatus(Reason):
    status: Literal["CONFIGURED", "DISABLED", "NEEDS_REVIEW", "NOT_AUTHORISED"]


class SourceInput(Timed):
    source_connection_id: UUID
    provider_item_key: str = Field(min_length=1, max_length=300)
    artifact_attachment_id: UUID | None = None
    source_issued_at: datetime | None = None
    retrieved_at: datetime
    source_reference: str = Field(min_length=1, max_length=500)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal["application/pdf", "application/xml", "application/json", "text/plain"]
    language: str = Field(default="en", max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class Geography(Timed):
    geometry_kind: Literal[
        "ROAD_EDGE_SET", "POLYGON", "MULTIPOLYGON", "DISTRICT", "STATE", "UNKNOWN"
    ]
    geojson: dict | None = None
    dataset_revision_id: UUID | None = None
    edge_keys: list[str] = Field(default_factory=list, max_length=1000)
    state_codes: list[str] = Field(default_factory=list, max_length=40)
    district_codes: list[str] = Field(default_factory=list, max_length=1000)
    direction: Literal["BOTH", "FORWARD", "REVERSE", "UNKNOWN"] = "UNKNOWN"
    precision: Literal["EXACT_EDGE", "SOURCE_POLYGON", "ADMIN_AREA", "APPROXIMATE", "UNKNOWN"]
    basis: Literal["SOURCE_DECLARED", "REVIEWED_MAPPING", "SIMULATION"]

    @field_validator("geojson")
    @classmethod
    def geometry(cls, value):
        if value is not None:
            from .geometry import validate_geometry

            validate_geometry(value)
        return value

    @model_validator(mode="after")
    def shape_consistency(self):
        if self.geometry_kind == "ROAD_EDGE_SET" and (
            not self.edge_keys or not self.dataset_revision_id
        ):
            raise ValueError("Exact edges require a retained dataset and nonempty keys")
        if self.geometry_kind in {"POLYGON", "MULTIPOLYGON"} and (
            not self.geojson
            or self.geojson.get("type")
            != self.geometry_kind.title().replace("Multipolygon", "MultiPolygon")
        ):
            raise ValueError("Polygon kind must match valid GeoJSON")
        if self.geometry_kind == "STATE" and not self.state_codes:
            raise ValueError("State-area events need state codes")
        if self.geometry_kind == "DISTRICT" and not self.district_codes:
            raise ValueError("District-area events need reviewed district codes")
        return self


class IncidentInput(Timed):
    environment: Mode
    visibility: Literal["PUBLIC_APPROVED", "ORG_ONLY", "CONSIGNMENT_ONLY", "RESTRICTED"] = (
        "ORG_ONLY"
    )
    consignment_id: UUID | None = None


class EventInput(Timed):
    source_item_id: UUID
    event_kind: Kind
    headline: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2000)
    source_sender: str = Field(min_length=1, max_length=200)
    source_identifier: str = Field(min_length=1, max_length=200)
    source_sent_at: datetime
    source_message_type: Literal["ALERT", "UPDATE", "CANCEL", "ACK", "ERROR", "NON_CAP"] = "NON_CAP"
    source_status: Literal["ACTUAL", "EXERCISE", "TEST", "DRAFT", "SYSTEM", "NON_CAP"] = "NON_CAP"
    upstream_references: list[str] = Field(default_factory=list, max_length=100)
    severity: str = Field(min_length=1, max_length=40)
    urgency: str | None = Field(default=None, max_length=40)
    certainty: str | None = Field(default=None, max_length=40)
    instructions: str | None = Field(default=None, max_length=2000)
    source_effective_raw: str | None = Field(default=None, max_length=100)
    source_expiry_raw: str | None = Field(default=None, max_length=100)
    assessed_effective_from: datetime | None = None
    assessed_effective_until: datetime | None = None
    operational_review_due_at: datetime
    time_interpretation: str = Field(min_length=1, max_length=500)
    geography: Geography
    vehicle_profile_codes: list[str] = Field(default_factory=list, max_length=20)
    cargo_profile_codes: list[str] = Field(default_factory=list, max_length=20)
    report_basis: Literal[
        "PRIMARY_SOURCE_OBSERVED",
        "CORROBORATED_REPORT",
        "SINGLE_REPORT",
        "CARRIER_REPORTED",
        "SIMULATION",
    ]
    independence_group: str | None = Field(default=None, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def window(self):
        if (
            self.assessed_effective_from
            and self.assessed_effective_until
            and self.assessed_effective_until <= self.assessed_effective_from
        ):
            raise ValueError("Event validity must be a positive half-open interval")
        return self


class PolicyInput(Timed):
    environment: Mode
    policy_code: str = Field(min_length=1, max_length=100)
    policy_class: Literal["APPLICATION_POLICY"] = "APPLICATION_POLICY"
    event_kinds: list[Kind] = Field(min_length=1, max_length=10)
    state_codes: list[str] = Field(default_factory=list, max_length=40)
    source_kinds: list[str] = Field(min_length=1, max_length=7)
    effect: Literal["EXCLUDE_EDGE", "REQUIRE_REVIEW", "ADVISORY_ONLY", "APPLY_DECLARED_DELAY_RANGE"]
    minimum_precision: Literal["EXACT_EDGE", "SOURCE_POLYGON", "ADMIN_AREA", "APPROXIMATE"]
    vehicle_profile_codes: list[str] = Field(default_factory=list, max_length=20)
    cargo_profile_codes: list[str] = Field(default_factory=list, max_length=20)
    maximum_source_age_seconds: int = Field(ge=60, le=604800)
    missing_coverage_action: Literal["REQUIRE_REVIEW", "SHOW_LIMITATION"]
    required_source_kinds: list[str] = Field(default_factory=list, max_length=7)
    delay_basis: Literal[
        "PROVIDER_ESTIMATE", "REVIEWED_OPERATIONAL_ASSUMPTION", "SIMULATION", "NONE"
    ] = "NONE"
    minimum_delay_seconds: int | None = Field(default=None, ge=0, le=604800)
    maximum_delay_seconds: int | None = Field(default=None, ge=0, le=604800)
    release_condition: Literal[
        "REOPENING_EVIDENCE",
        "WINDOW_END_AND_CURRENT_ASSESSMENT",
        "REVIEWED_RESOLUTION",
        "NOT_APPLICABLE",
    ]
    source_references: list[str] = Field(min_length=1, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    effective_from: datetime
    effective_until: datetime

    @model_validator(mode="after")
    def safe_policy(self):
        if self.effective_until <= self.effective_from:
            raise ValueError("Policy validity must have positive duration")
        if self.effect == "EXCLUDE_EDGE" and (
            set(self.event_kinds) - {"ROAD_CLOSURE", "TRAFFIC_RESTRICTION"}
            or self.minimum_precision not in {"EXACT_EDGE", "SOURCE_POLYGON"}
        ):
            raise ValueError("Only scoped closure/restriction evidence may exclude an edge")
        if self.effect == "APPLY_DECLARED_DELAY_RANGE" and (
            self.delay_basis == "NONE"
            or self.minimum_delay_seconds is None
            or self.maximum_delay_seconds is None
            or self.maximum_delay_seconds < self.minimum_delay_seconds
        ):
            raise ValueError("A delay range requires an explicit basis and ordered bounds")
        return self


class MappingInput(Timed):
    environment: Mode
    endpoint_contract_version: Literal["IMD_NOWCAST_V1", "IMD_DISTRICT_WARNING_V1", "CAP_1_2"]
    administrative_mapping: dict[str, str] = Field(default_factory=dict)
    boundary_dataset_reference: str = Field(min_length=1, max_length=500)
    source_references: list[str] = Field(min_length=1, max_length=20)
    effective_from: datetime
    effective_until: datetime
    limitations: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def window(self):
        if self.effective_until <= self.effective_from or len(self.administrative_mapping) > 1000:
            raise ValueError("Mapping must be bounded and have a valid effective window")
        return self


class Review(Exact):
    decision: Literal["APPROVE", "RETURN"]


class Reopening(Exact):
    reopening_event_revision_id: UUID


class Reassessment(Timed):
    expected_context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    current_route_plan_revision_id: UUID


class CaseInput(Reason):
    assessment_id: UUID
    current_route_plan_revision_id: UUID


class DriverInput(Reason):
    action: Literal[
        "ACKNOWLEDGE_ALERT",
        "REPORT_MOVING",
        "CONFIRM_REPORTED_STOPPED",
        "CANNOT_STOP_SAFELY",
        "REQUEST_ASSISTANCE",
    ]
    observed_at: datetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_meters: int | None = Field(default=None, ge=0, le=100000)
    location_method: Literal["GPS", "PIN", "NONE"]
    safe_stop: bool = False

    @model_validator(mode="after")
    def location(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Coordinates must be supplied together")
        if (self.location_method == "NONE") != (self.latitude is None):
            raise ValueError("Location method must match supplied coordinates")
        if self.action == "CONFIRM_REPORTED_STOPPED" and not self.safe_stop:
            raise ValueError("A stopped response requires the driver's safe-stop declaration")
        return self
