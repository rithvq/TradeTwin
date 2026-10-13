from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.trades.schemas import (
    DecimalString,
    Minor,
    NonnegativeDecimal,
    Phone,
    PositiveDecimal,
    Schema,
    partial,
    utc,
    valid_timezone,
)

PositiveMinor = Annotated[Minor, Field(pattern=r"^[0-9]*[1-9][0-9]*$", max_length=18)]
Attachments = list[UUID]


class CarrierProfileInput(Schema):
    service_type: Literal["CARRIER"] = "CARRIER"
    dispatch_contact_name: str = Field(min_length=1, max_length=100)
    dispatch_contact_phone_e164: Phone
    dispatch_contact_email: str | None = Field(default=None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    transporter_identifier_declared: str | None = Field(default=None, max_length=30)
    gst_registration_id: UUID | None = None
    directory_visibility: Literal["PRIVATE", "TRADING_PROFILE"]
    active: bool = True


class VehicleInput(Schema):
    registration_number: str = Field(min_length=3, max_length=20)
    vehicle_type: Literal[
        "VAN",
        "LIGHT_TRUCK",
        "MEDIUM_TRUCK",
        "HEAVY_TRUCK",
        "TRAILER",
        "REFRIGERATED_TRUCK",
        "OTHER",
    ]
    declared_payload_capacity_kg: PositiveDecimal
    declared_volume_capacity_m3: PositiveDecimal | None = None
    refrigerated: bool
    temperature_min_c: DecimalString | None = None
    temperature_max_c: DecimalString | None = None
    declared_hazardous_capable: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)
    active: bool = True

    @field_validator("registration_number")
    @classmethod
    def registration(cls, value):
        return value.upper()

    @model_validator(mode="after")
    def temperatures(self):
        if self.refrigerated and (
            self.temperature_min_c is None
            or self.temperature_max_c is None
            or self.temperature_min_c > self.temperature_max_c
        ):
            raise ValueError("Declare valid refrigerated temperature bounds")
        return self


VehiclePatch = partial(VehicleInput, "VehiclePatch")


class AllocationLine(Schema):
    line_ref: UUID
    allocated_quantity: PositiveDecimal
    uqc: str


class ConsignmentPlan(Schema):
    source_accepted_revision_id: UUID
    coordinating_organization_id: UUID
    planned_pickup_start: datetime
    planned_pickup_end: datetime
    expected_delivery_at: datetime
    pickup_contact_name: str = Field(min_length=1, max_length=100)
    pickup_contact_phone_e164: Phone
    delivery_contact_name: str = Field(min_length=1, max_length=100)
    delivery_contact_phone_e164: Phone
    declared_gross_weight_kg: PositiveDecimal
    declared_net_weight_kg: NonnegativeDecimal | None = None
    declared_volume_m3: PositiveDecimal | None = None
    package_type: Literal["CARTON", "BAG", "PALLET", "CRATE", "DRUM", "BULK", "OTHER"]
    package_count: int = Field(ge=0)
    packaging_notes: str | None = Field(default=None, max_length=1000)
    loading_notes: str | None = Field(default=None, max_length=1000)
    delivery_notes: str | None = Field(default=None, max_length=2000)
    items: list[AllocationLine] = Field(min_length=1)
    _utc = field_validator("planned_pickup_start", "planned_pickup_end", "expected_delivery_at")(
        utc
    )


ConsignmentPatch = partial(ConsignmentPlan, "ConsignmentPatch")


class AssignmentProposal(Schema):
    carrier_organization_id: UUID
    vehicle_id: UUID | None = None
    driver_user_id: UUID | None = None
    booking_start_at: datetime
    booking_end_at: datetime
    notes: str | None = Field(default=None, max_length=1000)
    _utc = field_validator("booking_start_at", "booking_end_at")(utc)


class AssignmentDecision(Schema):
    decision: Literal["ACCEPT", "DECLINE"]
    vehicle_id: UUID | None = None
    driver_user_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def required(self):
        if self.decision == "ACCEPT" and (not self.vehicle_id or not self.driver_user_id):
            raise ValueError("Acceptance requires a vehicle and driver")
        if self.decision == "DECLINE" and not self.reason:
            raise ValueError("Declining requires a reason")
        return self


class LoadedItem(Schema):
    consignment_item_id: UUID
    loaded_quantity: PositiveDecimal
    uqc: str


class PickupPayload(Schema):
    items: list[LoadedItem] = Field(min_length=1)
    actual_gross_weight_kg: PositiveDecimal
    actual_package_count: int = Field(ge=0)


class EtaPayload(Schema):
    expected_arrival_at: datetime
    reason: str = Field(min_length=1, max_length=1000)
    _utc = field_validator("expected_arrival_at")(utc)


class IncidentPayload(Schema):
    incident_type: Literal[
        "DELAY", "BREAKDOWN", "DAMAGE", "TEMPERATURE", "ROAD_OBSTRUCTION", "ACCIDENT", "OTHER"
    ]
    reported_severity: Literal["LOW", "MEDIUM", "HIGH"]
    description: str = Field(min_length=1, max_length=2000)
    observed_temperature_c: DecimalString | None = None
    expected_delay_minutes: int | None = Field(default=None, ge=0)


class ShipmentEventInput(Schema):
    client_event_id: UUID
    event_type: Literal[
        "PICKUP_CONFIRMED",
        "DEPARTED",
        "LOCATION_REPORTED",
        "ETA_UPDATED",
        "ARRIVED",
        "INCIDENT_REPORTED",
        "DELIVERY_HANDOVER_REPORTED",
    ]
    occurred_at: datetime
    assignment_id: UUID
    dispatch_authorization_id: UUID | None = None
    loading_manifest_revision_id: UUID | None = None
    latitude: Annotated[DecimalString, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[DecimalString, Field(ge=-180, le=180)] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    evidence_attachment_ids: Attachments = Field(default_factory=list)
    payload: PickupPayload | EtaPayload | IncidentPayload | Schema = Field(default_factory=Schema)
    _utc = field_validator("occurred_at")(utc)

    @model_validator(mode="before")
    @classmethod
    def event_payload(cls, values):
        if isinstance(values, dict):
            values = dict(values)
            model = {
                "PICKUP_CONFIRMED": PickupPayload,
                "ETA_UPDATED": EtaPayload,
                "INCIDENT_REPORTED": IncidentPayload,
            }.get(values.get("event_type"), Schema)
            values["payload"] = model.model_validate(values.get("payload", {}))
            if values.get("event_type") == "LOCATION_REPORTED" and (
                values.get("latitude") is None or values.get("longitude") is None
            ):
                raise ValueError("Location requires latitude and longitude")
        return values


class ReceiptLineInput(Schema):
    consignment_item_id: UUID
    delivered_quantity: PositiveDecimal
    uqc: str
    observed_condition: Literal["GOOD", "DAMAGED", "TEMPERATURE_EXCEPTION", "OTHER"]
    condition_notes: str | None = Field(default=None, max_length=1000)


class ReceiptInput(Schema):
    client_receipt_id: UUID
    received_at: datetime
    received_package_count: int | None = Field(default=None, ge=0)
    delivery_reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    evidence_attachment_ids: Attachments = Field(default_factory=list)
    lines: list[ReceiptLineInput] = Field(min_length=1)
    _utc = field_validator("received_at")(utc)


class ReceiptCorrection(ReceiptInput):
    reason: str = Field(min_length=1, max_length=1000)


class InspectionInput(Schema):
    receipt_line_id: UUID
    accepted_quantity: NonnegativeDecimal
    rejected_quantity: NonnegativeDecimal
    rejection_reason: (
        Literal["DAMAGE", "QUALITY", "SPECIFICATION", "TEMPERATURE", "OTHER"] | None
    ) = None
    notes: str | None = Field(default=None, max_length=2000)
    evidence_attachment_ids: Attachments = Field(default_factory=list)

    @model_validator(mode="after")
    def quantities(self):
        if self.accepted_quantity + self.rejected_quantity <= 0:
            raise ValueError("At least one decision quantity must be positive")
        if self.rejected_quantity > 0 and not self.rejection_reason:
            raise ValueError("A rejection requires its reason")
        return self


class InspectionBatch(Schema):
    decisions: list[InspectionInput] = Field(min_length=1)


class Reason(Schema):
    reason: str = Field(min_length=1, max_length=1000)


class Notes(Schema):
    notes: str | None = Field(default=None, max_length=2000)


class DisputeInput(Schema):
    consignment_id: UUID | None = None
    receipt_line_id: UUID | None = None
    payment_id: UUID | None = None
    dispute_type: Literal[
        "SHORTAGE", "DAMAGE", "QUALITY", "TEMPERATURE", "DELAY", "PAYMENT", "OTHER"
    ]
    summary: str = Field(min_length=1, max_length=1000)
    requested_remedy: str | None = Field(default=None, max_length=2000)
    disputed_quantity: PositiveDecimal | None = None
    uqc: str | None = None
    disputed_amount_minor: Minor | None = None
    evidence_attachment_ids: Attachments = Field(default_factory=list)

    @model_validator(mode="after")
    def unit(self):
        if self.disputed_quantity is not None and not self.uqc:
            raise ValueError("Disputed quantities require UQC")
        return self


class Comment(Schema):
    text: str = Field(min_length=1, max_length=2000)
    evidence_attachment_ids: Attachments = Field(default_factory=list)


class ResolutionProposal(Schema):
    outcome: Literal[
        "ACKNOWLEDGE_FACTS",
        "INSPECT_AGAIN",
        "COMMERCIAL_ADJUSTMENT_REQUESTED",
        "RETURN_REQUESTED",
        "OTHER",
    ]
    resolution_text: str = Field(min_length=1, max_length=2000)


class ResolutionDecision(Schema):
    decision: Literal["ACCEPT", "REJECT"]
    proposal_id: UUID
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def rejection(self):
        if self.decision == "REJECT" and not self.reason:
            raise ValueError("Rejecting requires a reason")
        return self


Trigger = Literal[
    "ORDER_CONFIRMATION", "FULL_DISPATCH", "FULL_DELIVERY", "FULL_ACCEPTANCE", "FIXED_DATE"
]


class ScheduleLineInput(Schema):
    obligation_ref: UUID | None = None
    label: str = Field(min_length=1, max_length=100)
    face_amount_minor: Minor
    trigger: Trigger
    offset_days: int = Field(default=0, ge=0)
    fixed_due_on: date | None = None

    @model_validator(mode="after")
    def fixed_date(self):
        if (self.trigger == "FIXED_DATE") != (self.fixed_due_on is not None):
            raise ValueError("Only FIXED_DATE requires a fixed due date")
        return self


class PaymentScheduleInput(Schema):
    accepted_revision_id: UUID
    reason: str | None = Field(default=None, max_length=1000)
    due_timezone: str = "Asia/Kolkata"
    lines: list[ScheduleLineInput] = Field(min_length=1)
    _timezone = field_validator("due_timezone")(valid_timezone)


class ScheduleApproval(Schema):
    decision: Literal["ACCEPT", "REJECT"]
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, max_length=1000)


class PaymentInput(Schema):
    amount_minor: PositiveMinor
    paid_on: date
    method: Literal["BANK_TRANSFER", "UPI", "CASH", "CHEQUE", "OTHER"]
    declared_reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    evidence_attachment_ids: Attachments = Field(default_factory=list)


class AllocationInput(Schema):
    obligation_ref: UUID
    amount_minor: PositiveMinor


class PaymentAllocationBatch(Schema):
    allocations: list[AllocationInput] = Field(min_length=1)


class AllocationReversal(Reason):
    amount_minor: PositiveMinor


class VoidDecision(Schema):
    void_request_id: UUID
    decision: Literal["APPROVE", "REJECT"]
    reason: str | None = Field(default=None, max_length=1000)


class AttachmentUploadInput(Schema):
    trade_id: UUID
    consignment_id: UUID | None = None
    purpose: Literal[
        "POD",
        "PICKUP",
        "INCIDENT",
        "RECEIPT",
        "PAYMENT",
        "OTHER",
        "DOCUMENT_FINANCIAL",
        "DOCUMENT_OPERATIONAL",
    ]
    original_name: str = Field(min_length=1, max_length=200)
    content_type: Literal["application/pdf", "image/jpeg", "image/png", "application/json"]
    size_bytes: int = Field(gt=0, le=20 * 1024 * 1024)


class AttachmentCompletion(Schema):
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
