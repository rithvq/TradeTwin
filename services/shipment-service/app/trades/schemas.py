"""Shared wire validators. Decimal inputs are strings; computed fields are never inputs."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, get_args, get_origin
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)

from .reference import ROLE_PERMISSIONS, STATES, UQC


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def decimal_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d{1,6})?", value):
        raise ValueError("Use a decimal string with at most six decimal places")
    if len(value.split(".")[0].lstrip("-")) > 14:
        raise ValueError("Decimal exceeds numeric(20,6)")
    return Decimal(value)


DecimalString = Annotated[Decimal, BeforeValidator(decimal_string)]
PositiveDecimal = Annotated[DecimalString, Field(gt=0)]
NonnegativeDecimal = Annotated[DecimalString, Field(ge=0)]
Minor = Annotated[str, Field(pattern=r"^\d{1,18}$")]
Phone = Annotated[str, Field(pattern=r"^\+[1-9]\d{7,14}$")]
Role = Literal["SELLER", "BUYER"]
Position = Literal["REGISTERED", "UNREGISTERED", "EXEMPTION_CLAIMED", "NOT_PROVIDED"]


def state(value):
    if value not in STATES:
        raise ValueError("Select a supported state code")
    return value


def valid_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Use an IANA timezone") from exc
    return value


def utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Include a timezone offset")
    return value.astimezone(UTC)


class Address(Schema):
    address_line1: str = Field(min_length=1, max_length=120)
    address_line2: str | None = Field(default=None, max_length=120)
    locality: str | None = Field(default=None, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    state_code: str
    postal_code: str = Field(pattern=r"^[1-9]\d{5}$")
    country_code: Literal["IN"] = "IN"
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone_e164: Phone | None = None
    timezone: str = "Asia/Kolkata"
    _state = field_validator("state_code")(state)
    _timezone = field_validator("timezone")(valid_timezone)


class OrganizationFields(Schema):
    legal_name: str = Field(min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    entity_type: Literal[
        "PROPRIETORSHIP", "PARTNERSHIP", "LLP", "COMPANY", "TRUST", "SOCIETY", "OTHER"
    ]
    authorised_contact_name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    mobile_e164: Phone
    registered_address: Address
    registration_position: Position
    registration_explanation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def explanation(self):
        if (
            self.registration_position in {"UNREGISTERED", "EXEMPTION_CLAIMED"}
            and not self.registration_explanation
        ):
            raise ValueError("Explain the declared registration position")
        return self


def partial(model, name):
    fields = {}
    for key, info in model.model_fields.items():
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, Schema):
            annotation = partial(annotation, f"Partial{annotation.__name__}")
        elif get_origin(annotation) is list:
            inner = get_args(annotation)[0]
            if isinstance(inner, type) and issubclass(inner, Schema):
                annotation = list[partial(inner, f"Partial{inner.__name__}")]
        elif type(None) in get_args(annotation):
            inner = next(
                (
                    item
                    for item in get_args(annotation)
                    if isinstance(item, type) and issubclass(item, Schema)
                ),
                None,
            )
            if inner:
                annotation = partial(inner, f"Partial{inner.__name__}") | None
        optional = (
            Annotated[annotation | None, *info.metadata] if info.metadata else annotation | None
        )
        fields[key] = (optional, None)
    return create_model(name, __base__=Schema, **fields)


OrganizationDraft = partial(OrganizationFields, "OrganizationDraft")


def gstin_format(value):
    value = value.upper()
    if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value):
        raise ValueError("Use a 15-character GSTIN in the declared format")
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for index, char in enumerate(value[:14]):
        product = alphabet.index(char) * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    if alphabet[(36 - total % 36) % 36] != value[-1]:
        raise ValueError("GSTIN checksum is invalid; this is format validation only")
    return value


class RegistrationCreate(Schema):
    gstin: str
    state_code: str
    declared_taxpayer_scheme: Literal["REGULAR", "COMPOSITION", "OTHER", "UNKNOWN"]
    declared_establishment_kind: Literal["NORMAL", "SEZ_UNIT", "SEZ_DEVELOPER", "UNKNOWN"]
    _gstin = field_validator("gstin")(gstin_format)
    _state = field_validator("state_code")(state)

    @model_validator(mode="after")
    def matching_state(self):
        if self.gstin[:2] != self.state_code:
            raise ValueError("GSTIN prefix must match the declared state")
        return self


class LocationCreate(Schema):
    registration_id: UUID | None = None
    label: str = Field(min_length=1, max_length=100)
    location_type: Literal["OFFICE", "WAREHOUSE", "FACTORY", "STORE", "OTHER"]
    address: Address
    visibility: Literal["PRIVATE", "TRADING_PROFILE"]


class PartyInput(Schema):
    organization_id: UUID | None = None
    registration_id: UUID | None = None
    billing_address: Address | None = None


class GoodsLine(Schema):
    line_ref: UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    specification: str = Field(min_length=1, max_length=2000)
    hsn_code: str | None = Field(default=None, pattern=r"^\d{2,8}$")
    hsn_confirmation: Literal["NOT_PROVIDED", "SUGGESTED", "USER_CONFIRMED"]
    quantity: PositiveDecimal
    uqc: str
    unit_price_minor: NonnegativeDecimal
    discount_minor: Minor = "0"
    declared_tax_rate_percent: (
        Annotated[DecimalString, Field(ge=0, le=100, decimal_places=4)] | None
    ) = None
    estimated_gross_weight_kg: PositiveDecimal | None = None
    package_count_estimate: int | None = Field(default=None, ge=0)
    hazardous_declared: bool
    temperature_controlled: bool
    temperature_min_c: DecimalString | None = None
    temperature_max_c: DecimalString | None = None
    fragile: bool
    stackable: bool

    @field_validator("uqc")
    @classmethod
    def unit(cls, value):
        if value not in UQC:
            raise ValueError("Select a maintained unit code")
        return value


GoodsDraft = partial(GoodsLine, "GoodsDraft")


class PaymentMilestone(Schema):
    label: str = Field(min_length=1, max_length=100)
    percent_of_quoted_goods: PositiveDecimal
    trigger: Literal["ORDER_CONFIRMATION", "DISPATCH", "DELIVERY", "ACCEPTANCE", "FIXED_DATE"]
    due_on: date | None = None


class CommercialTerms(Schema):
    freight_payer: Literal["SELLER", "BUYER", "SHARED"]
    seller_freight_share_percent: Annotated[DecimalString, Field(ge=0, le=100)] | None = None
    freight_included_in_goods_price: bool
    freight_estimate_minor: Minor | None = None
    loading_responsibility: Literal["SELLER", "BUYER", "CARRIER"]
    unloading_responsibility: Literal["SELLER", "BUYER", "CARRIER"]
    insurance_required: bool
    insurance_responsibility: Literal["SELLER", "BUYER", "CARRIER", "NONE"]
    payment_mode: Literal["ADVANCE", "ON_DELIVERY", "CREDIT", "MILESTONE"]
    advance_minor: Minor | None = None
    credit_days: int | None = Field(default=None, ge=0)
    milestone_schedule: list[PaymentMilestone] = Field(default_factory=list)
    acceptance_window_hours: int = Field(gt=0)
    quality_acceptance_criteria: str = Field(min_length=1, max_length=2000)
    return_policy: str = Field(min_length=1, max_length=2000)
    cancellation_terms: str = Field(min_length=1, max_length=2000)
    partial_delivery_allowed: bool
    supplier_substitution_allowed: bool
    pickup_location_substitution_allowed: bool
    commercial_valid_until: datetime
    _utc = field_validator("commercial_valid_until")(utc)


class DeliveryRequirements(Schema):
    mode: Literal["ROAD"]
    pickup_earliest_at: datetime
    pickup_latest_at: datetime
    delivery_deadline_at: datetime
    receiving_window_start_local: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    receiving_window_end_local: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    receiving_timezone: str
    receiving_window_crosses_midnight: bool
    consolidation_allowed: bool
    return_truck_allowed: bool
    maximum_transshipments: int = Field(ge=0)
    delivery_notes: str | None = Field(default=None, max_length=2000)
    _utc = field_validator("pickup_earliest_at", "pickup_latest_at", "delivery_deadline_at")(utc)
    _timezone = field_validator("receiving_timezone")(valid_timezone)


class TradeFacts(Schema):
    scope: Literal["DOMESTIC_INTERSTATE"]
    movement_purpose: Literal["SALE"]
    seller_organization_id: UUID
    buyer_organization_id: UUID
    seller_registration_id: UUID | None = None
    buyer_registration_id: UUID | None = None
    bill_from: PartyInput
    bill_to: PartyInput
    dispatch_from: Address
    ship_to: Address
    transaction_layout: Literal[
        "REGULAR", "BILL_TO_SHIP_TO", "BILL_FROM_DISPATCH_FROM", "COMBINATION"
    ]
    purchase_order_reference: str | None = Field(default=None, max_length=100)
    currency: Literal["INR"]
    pricing_basis: Literal["NET_TAX_EXTRA", "GROSS_TAX_INCLUDED"]
    tax_terms: str = Field(min_length=1, max_length=1000)
    items: list[GoodsLine] = Field(min_length=1, max_length=100)
    commercial_terms: CommercialTerms
    delivery_requirements: DeliveryRequirements


TradeDraft = partial(TradeFacts, "TradeDraftBase")
TradeDraft = create_model(
    "TradeDraft",
    __base__=TradeDraft,
    items=(list[GoodsDraft] | None, Field(default=None, max_length=100)),
)


class TradeCreate(Schema):
    initiated_by_role: Role
    facts: TradeDraft = Field(default_factory=TradeDraft)


class DraftPatch(Schema):
    base_revision_id: UUID
    changes: TradeDraft


class Publish(Schema):
    revision_id: UUID
    commercial_valid_until: datetime
    _utc = field_validator("commercial_valid_until")(utc)


class Confirmation(Schema):
    revision_id: UUID
    terms_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Rejection(Confirmation):
    reason: str = Field(min_length=1, max_length=2000)


class Reason(Schema):
    reason: str = Field(min_length=1, max_length=2000)


class AmendmentCreate(Reason):
    base_accepted_revision_id: UUID


class MembershipChange(Schema):
    user_id: UUID
    status: Literal["ACTIVE", "SUSPENDED"] = "ACTIVE"
    capabilities: list[str]
    trade_id: UUID | None = None
    expires_at: datetime | None = None

    @field_validator("capabilities")
    @classmethod
    def roles(cls, values):
        if not values or any(value not in ROLE_PERMISSIONS for value in values):
            raise ValueError("Select explicit capability roles")
        return sorted(set(values))

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        return utc(value) if value else None


class ErrorField(Schema):
    path: str
    code: str
    message: str


class ErrorDetail(Schema):
    code: str
    message: str
    request_id: UUID
    field_errors: list[ErrorField]
    retryable: bool


class ErrorResponse(Schema):
    error: ErrorDetail


class RevisionView(Schema):
    id: UUID
    revision_number: int
    revision_kind: str
    facts: dict
    pricing_summary: dict
    terms_hash: str
    created_at: datetime


class TradeView(Schema):
    trade_id: UUID
    execution_mode: Literal["PRODUCTION", "SIMULATION"] = "PRODUCTION"
    reference: str
    agreement_status: Literal["DRAFT", "OFFERED", "CONFIRMED", "CANCELLED"]
    accepted_revision: RevisionView | None
    current_candidate_revision: RevisionView | None
    current_revision_id: UUID | None
    revision_number: int
    active_offer: dict | None
    pending_amendment: dict | None
    approval_progress: list[dict]
    pricing_summary: dict
    next_actions: list[str]
    next_action_owners: list[dict] = Field(default_factory=list)
    counterparty: dict | None = None
    validation_errors: list[ErrorField]
    dispatch_readiness: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    etag: str
