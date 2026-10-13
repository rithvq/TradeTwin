"""Strict command schemas: quantities are decimal strings, money is integer paise."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator, model_validator

from app.trades.reference import STATES
from app.trades.schemas import Schema

M = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,17})$")]
Q = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=6)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
IDs = Annotated[list[UUID], Field(max_length=30)]
Category = Literal[
    "TOLL", "FUEL_SURCHARGE", "LOADING", "UNLOADING", "HANDLING", "CARGO_INSURANCE", "OTHER"
]


class Timed(Schema):
    @field_validator("*", mode="after")
    @classmethod
    def utc(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("UTC RFC3339 timestamp with timezone required")
            from datetime import UTC

            return value.astimezone(UTC)
        return value


class Reason(Schema):
    reason: str = Field(min_length=1, max_length=2000)


class HashCommand(Schema):
    content_hash: Hash
    reason: str = Field(default="Exact revision accepted", min_length=1, max_length=2000)


class RequestHashCommand(Schema):
    request_hash: Hash = Field(validation_alias=AliasChoices("request_hash", "content_hash"))
    reason: str = Field(default="Exact request accepted", min_length=1, max_length=2000)

    @property
    def content_hash(self):
        return self.request_hash


class QuoteHashCommand(Schema):
    quote_hash: Hash = Field(validation_alias=AliasChoices("quote_hash", "content_hash"))
    reason: str = Field(default="Exact offer accepted", min_length=1, max_length=2000)

    @property
    def content_hash(self):
        return self.quote_hash


class InvitationInput(Schema):
    carrier_organisation_ids: list[UUID] = Field(min_length=1, max_length=30)


class LocationInput(Schema):
    address_role: Literal["PICKUP", "DROP"]
    accepted_address_hash: Hash
    latitude: Decimal = Field(ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=10, decimal_places=7)
    position_source: Literal["USER_PIN", "LICENSED_GEOCODER", "SIMULATION"]
    precision: Literal["CONFIRMED_LOADING_GATE", "PREMISES", "AREA_CENTROID", "UNKNOWN"]
    accuracy_meters: Q | None = None
    state_code: str
    provider_reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    state_coordinate_conflict_resolved: bool = False

    @field_validator("state_code")
    @classmethod
    def state(cls, value):
        if value not in STATES:
            raise ValueError("Use the current versioned GST state reference")
        return value


class ProfileInput(Schema):
    combined_tare_weight_kg: Q | None = None
    maximum_authorised_combined_weight_kg: Q | None = None
    overall_height_mm: int | None = Field(default=None, gt=0)
    overall_width_mm: int | None = Field(default=None, gt=0)
    overall_length_mm: int | None = Field(default=None, gt=0)
    axle_count: int | None = Field(default=None, gt=0)
    maximum_actual_axle_load_kg: Q | None = None
    trailer_count: int = Field(default=0, ge=0)
    toll_vehicle_class_code: str | None = Field(default=None, max_length=50)
    speed_cap_kph: int | None = Field(default=None, gt=0, le=150)
    supported_cargo_profile_codes: list[str] = Field(default_factory=list, max_length=30)
    source_document_version_ids: IDs = []
    transport_evidence_revision_ids: IDs = []
    field_provenance: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class Node(Schema):
    node_key: str = Field(min_length=1, max_length=100)
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    state_code: str
    node_kind: Literal["PICKUP_ACCESS", "DROP_ACCESS", "JUNCTION", "APPROVED_STOP"]


class Edge(Schema):
    edge_key: str = Field(min_length=1, max_length=100)
    from_node_key: str
    to_node_key: str
    directed: bool = True
    distance_meters: int = Field(gt=0)
    estimated_driving_seconds: int = Field(gt=0)
    ordered_state_sequence: list[str] | None
    allowed_vehicle_profile_codes: list[str]
    maximum_height_mm: int | None = Field(default=None, gt=0)
    maximum_width_mm: int | None = Field(default=None, gt=0)
    maximum_length_mm: int | None = Field(default=None, gt=0)
    maximum_loaded_weight_kg: Q | None = None
    maximum_axle_load_kg: Q | None = None
    restriction_refs: list[dict] = []
    toll_record_refs: list[dict] = []
    assessment_coverage: dict[str, Literal["ASSESSED_UNRESTRICTED", "ASSESSED_LIMIT", "UNKNOWN"]]
    limitations: list[str] = []


class PlanningPolicy(Schema):
    policy_code: Literal["BASELINE_ROAD_V1"] = "BASELINE_ROAD_V1"
    accepted_location_precisions: list[Literal["CONFIRMED_LOADING_GATE", "PREMISES"]] = Field(
        default_factory=lambda: ["CONFIRMED_LOADING_GATE"], min_length=1, max_length=2
    )
    cost_assumption_independent_review_required: Literal[True] = True
    missing_restrictions_block_ranking: Literal[True] = True
    hard_constraints_not_weightable: Literal[True] = True


class DatasetInput(Timed):
    dataset_code: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    source_kind: Literal["SIMULATION_FIXTURE", "LICENSED_PROVIDER", "MANUAL_OPERATIONAL_RECORD"]
    source_reference: str = Field(min_length=1, max_length=2000)
    supported_state_codes: list[str]
    supported_vehicle_profile_codes: list[str]
    observed_at: datetime | None = None
    valid_from: datetime
    valid_until: datetime | None = None
    attribution_text: str
    license_reference: str
    retention_policy: Literal["PERMITTED_ARCHIVE", "UNTIL_DATE", "NO_CONTENT_STORAGE"]
    retention_until: datetime | None = None
    export_allowed: bool
    limitations: list[str]
    nodes: list[Node] = Field(min_length=2, max_length=200)
    edges: list[Edge] = Field(min_length=1, max_length=500)
    planning_policy: PlanningPolicy = Field(default_factory=PlanningPolicy)

    @model_validator(mode="after")
    def connected(self):
        keys = {n.node_key for n in self.nodes}
        if len(keys) != len(self.nodes) or len({e.edge_key for e in self.edges}) != len(self.edges):
            raise ValueError("Graph node and edge keys must be unique")
        if any(e.from_node_key not in keys or e.to_node_key not in keys for e in self.edges):
            raise ValueError("Every edge must reference retained nodes")
        return self


class GenerateInput(Timed):
    pickup_location_revision_id: UUID
    drop_location_revision_id: UUID
    vehicle_profile_revision_id: UUID
    departure_at: datetime
    dataset_revision_id_or_provider_connection_id: UUID
    objective: Literal["DISTANCE", "TIME"] = "TIME"
    maximum_alternatives: int = Field(default=3, ge=1, le=3)


class RFQInput(Timed):
    pickup_location_revision_id: UUID
    drop_location_revision_id: UUID
    requested_route_template_revision_ids: list[UUID] = Field(min_length=1, max_length=20)
    requested_pickup_window_start: datetime
    requested_pickup_window_end: datetime
    required_arrival_by: datetime | None = None
    service_requirement_codes: list[Category] = Field(
        default_factory=lambda: ["TOLL", "FUEL_SURCHARGE"]
    )
    invited_carrier_organisation_ids: list[UUID] = Field(min_length=1, max_length=30)
    response_deadline: datetime
    supersedes_rfq_id: UUID | None = None
    request_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def window(self):
        if self.requested_pickup_window_end <= self.requested_pickup_window_start:
            raise ValueError("Pickup window must have positive duration")
        return self


class Charge(Schema):
    component_id: UUID
    component_code: Literal[
        "BASE_FREIGHT",
        "TOLL",
        "FUEL_SURCHARGE",
        "LOADING",
        "UNLOADING",
        "HANDLING",
        "INSURANCE",
        "OTHER",
    ]
    label: str = Field(min_length=1, max_length=100)
    amount_minor: M


class Coverage(Schema):
    category_code: Category
    coverage: Literal[
        "INCLUDED_IN_QUOTED_PRICE", "EXCLUDED_PAYER_COST", "NOT_APPLICABLE", "UNKNOWN"
    ]
    explanation: str = Field(min_length=1, max_length=1000)


class WaitTerm(Schema):
    code: Literal["ORIGIN_WAIT", "DESTINATION_WAIT"]
    free_minutes: int = Field(ge=0)
    billing_increment_minutes: int = Field(gt=0)
    charge_per_increment_gross_minor: M
    maximum_charge_gross_minor: M | None = None
    applicability_note: str = Field(min_length=1, max_length=1000)


class QuoteInput(Timed):
    quote_head_id: UUID | None = None
    route_template_revision_id: UUID
    vehicle_id: UUID
    routing_vehicle_profile_revision_id: UUID
    driver_user_id: UUID
    transport_evidence_revision_ids: IDs = []
    offered_pickup_window_start: datetime
    offered_pickup_window_end: datetime
    offered_delivery_window_start: datetime
    offered_delivery_window_end: datetime
    booking_window_start: datetime
    booking_window_end: datetime
    delivery_commitment_kind: Literal["TARGET_ONLY", "CONTRACTUAL_DEADLINE"] = "TARGET_ONLY"
    delivery_terms: str = Field(min_length=1, max_length=2000)
    currency: Literal["INR"] = "INR"
    offer_kind: Literal["FIRM_OFFER", "INDICATIVE"]
    pricing_basis: Literal["FIXED_FOR_CONSIGNMENT_AND_ROUTE"] = "FIXED_FOR_CONSIGNMENT_AND_ROUTE"
    charge_components: list[Charge] = Field(min_length=1, max_length=20)
    discount_minor: M = "0"
    carrier_charged_tax_minor: M | None
    tax_treatment: Literal[
        "DECLARED_SUPPLIER_CHARGED", "DECLARED_RECIPIENT_ACCOUNTED", "DECLARED_NO_TAX", "UNRESOLVED"
    ]
    tax_note: str | None = Field(default=None, max_length=2000)
    service_coverage: list[Coverage] = Field(max_length=10)
    unpriced_carrier_extras_allowed: Literal[False] = False
    contingent_charge_terms: list[WaitTerm] = Field(default_factory=list, max_length=10)
    cancellation_terms: str = Field(min_length=1, max_length=4000)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    price_limitations: list[str] = Field(default_factory=list, max_length=20)
    valid_from: datetime
    accept_by: datetime
    source_mode: Literal["PORTAL_ENTRY", "REVIEWED_QUOTE_DOCUMENT", "SIMULATION"] = "PORTAL_ENTRY"
    quote_document_version_id: UUID | None = None
    quote_document_fact_revision_id: UUID | None = None
    carrier_offer_reference: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def consistent(self):
        if int(self.discount_minor) > sum(int(c.amount_minor) for c in self.charge_components):
            raise ValueError("Discount exceeds fixed component subtotal")
        if self.tax_treatment == "DECLARED_NO_TAX" and self.carrier_charged_tax_minor != "0":
            raise ValueError("Declared no-tax requires explicit zero")
        if self.tax_treatment == "UNRESOLVED" and self.carrier_charged_tax_minor is not None:
            raise ValueError("Unresolved tax cannot be declared as zero")
        if self.accept_by <= self.valid_from:
            raise ValueError("Offer acceptance window must have positive duration")
        if not (
            self.booking_window_start
            <= self.offered_pickup_window_start
            < self.offered_pickup_window_end
            <= self.booking_window_end
            and self.booking_window_start
            <= self.offered_delivery_window_start
            < self.offered_delivery_window_end
            <= self.booking_window_end
        ):
            raise ValueError("Booking must cover all offered service windows")
        for values, key in [
            (self.service_coverage, "category_code"),
            (self.contingent_charge_terms, "code"),
            (self.charge_components, "component_id"),
        ]:
            if len({getattr(c, key) for c in values}) != len(values):
                raise ValueError("Duplicate charge, coverage or contingent term")
        if self.source_mode == "REVIEWED_QUOTE_DOCUMENT" and not (
            self.quote_document_version_id and self.quote_document_fact_revision_id
        ):
            raise ValueError(
                "Reviewed offer requires exact document and effective review references"
            )
        return self


class ExternalCost(Timed):
    component_id: UUID
    category: Category
    label: str = Field(min_length=1, max_length=100)
    applies_to_quote_revision_ids: IDs
    basis: Literal["FIXED", "PER_KM", "PER_KG", "PER_PACKAGE"]
    fixed_amount_minor: M | None = None
    rate_minor_per_unit: Q | None = None
    quantity_source: Literal["ROUTE_DISTANCE_KM", "CARGO_GROSS_KG", "PACKAGE_COUNT", "FIXED"]
    fixed_quantity: Q | None = None
    amount_includes_applicable_tax: bool | None = None
    source_kind: Literal["REVIEWED_EXTERNAL_OFFER", "USER_ESTIMATE", "LICENSED_DATA", "SIMULATION"]
    source_reference: dict | None = None
    valid_until: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)


class RecipientTax(Schema):
    quote_revision_id: UUID
    amount_minor: M | None
    basis_document_version_ids: IDs = []
    declaration_note: str = Field(min_length=1, max_length=2000)


class AssumptionsInput(Schema):
    comparison_policy: Literal["QUOTED_AMOUNTS_ONLY", "ALLOW_DECLARED_ESTIMATES"]
    external_cost_components: list[ExternalCost] = Field(default_factory=list, max_length=30)
    recipient_tax_cash_estimates: list[RecipientTax] = Field(default_factory=list, max_length=30)


class ReviewInput(Reason):
    decision: Literal["APPROVE_DECLARATION", "RETURN_FOR_CORRECTION"]


class Scenario(Schema):
    scenario_code: Literal["BASE", "EXTRA_WAIT", "EXTRA_STOP"]
    label: str = Field(min_length=1, max_length=100)
    delay_placement: Literal["ORIGIN_BEFORE_DEPARTURE", "IN_TRANSIT", "DESTINATION_UNLOADING"]
    additional_wait_minutes: int = Field(default=0, ge=0, le=43200)
    additional_stop_minutes: int = Field(default=0, ge=0, le=43200)
    assumption_origin: Literal["USER_INPUT", "PUBLISHED_QUOTE_TERM", "SIMULATION"]
    assumption_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def base(self):
        if self.scenario_code == "BASE" and (
            self.additional_wait_minutes or self.additional_stop_minutes
        ):
            raise ValueError("BASE cannot contain stress delay; create a new planning intent")
        return self


class Intent(Timed):
    intended_pickup_at: datetime
    intended_departure_at: datetime
    required_arrival_by: datetime | None = None
    planned_stop_seconds: int = Field(default=0, ge=0, le=86400)
    planned_stops: list[dict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def timing(self):
        if self.intended_departure_at < self.intended_pickup_at:
            raise ValueError("Departure cannot precede pickup")
        if (
            self.planned_stops
            and sum(s.get("duration_seconds", 0) for s in self.planned_stops)
            != self.planned_stop_seconds
        ):
            raise ValueError("Stop durations must equal the declared planned-stop total")
        return self


class Weights(Schema):
    cost_basis_points: int = Field(default=5000, ge=0, le=10000)
    time_basis_points: int = Field(default=5000, ge=0, le=10000)

    @model_validator(mode="after")
    def sum(self):
        if self.cost_basis_points + self.time_basis_points != 10000:
            raise ValueError("Balanced weights must sum to 10000")
        return self


Objective = Literal["LOWEST_COMPARABLE_COST", "EARLIEST_ESTIMATED_ARRIVAL", "BALANCED"]


class RunInput(Schema):
    expected_context_version: int = Field(ge=0)
    planning_intent: Intent
    quote_revision_ids: list[UUID] = Field(min_length=1, max_length=30)
    route_template_revision_ids: list[UUID] = Field(min_length=1, max_length=20)
    cost_assumption_revision_id: UUID | None = None
    objective: Objective = "LOWEST_COMPARABLE_COST"
    balanced_weights: Weights = Field(default_factory=Weights)
    comparison_policy: Literal["QUOTED_AMOUNTS_ONLY", "ALLOW_DECLARED_ESTIMATES"] = (
        "QUOTED_AMOUNTS_ONLY"
    )
    scenarios: list[Scenario] = Field(default_factory=list, max_length=5)
    parent_run_id: UUID | None = None

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.quote_revision_ids)) != len(self.quote_revision_ids) or len(
            {s.scenario_code for s in self.scenarios}
        ) != len(self.scenarios):
            raise ValueError("Quote revisions and scenario codes must be unique")
        return self


class ScenarioRun(Schema):
    scenario: Scenario
    objective: Objective
    balanced_weights: Weights = Field(default_factory=Weights)


class SelectionInput(Schema):
    run_id: UUID
    candidate_id: UUID
    candidate_hash: Hash
    quote_revision_id: UUID
    quote_hash: Hash
    scenario_code: Literal["BASE"]
    expected_existing_assignment_id: UUID | None
    expected_consignment_row_version: int = Field(ge=1)
    expected_context_version: int = Field(ge=0)


class SelectionDecision(Reason):
    proposal_hash: Hash
    quote_hash: Hash
    decision: Literal["APPROVE", "REJECT"]
    acknowledged_limitation_codes: list[str] = []


class CarrierDecision(Reason):
    proposal_hash: Hash
    quote_hash: Hash
    proposed_assignment_id: UUID
    decision: Literal["ACCEPT", "DECLINE"]


class CancellationInput(Reason):
    commitment_hash: Hash
    proposed_fee_position: Literal["NO_FEE", "AGREED_AMOUNT"]
    proposed_fee_minor: M
    proposed_fee_note: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def fee(self):
        if self.proposed_fee_position == "NO_FEE" and self.proposed_fee_minor != "0":
            raise ValueError("No-fee position requires explicit zero")
        return self


class CancellationDecisionInput(Reason):
    proposal_hash: Hash
    decision_role: Literal["PAYER", "COORDINATOR", "CARRIER"]
    decision: Literal["APPROVE", "REJECT"]
