from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.trades.models import JSON_TYPE, Mutable, Record, TradeBase

Q = Numeric(20, 6)
ID = Uuid(as_uuid=False)
TS = DateTime(timezone=True)


class Carrier(Mutable, TradeBase):
    __tablename__ = "op_carrier_profiles"
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), unique=True)
    profile_json: Mapped[dict] = mapped_column(JSON_TYPE)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Vehicle(Mutable, TradeBase):
    __tablename__ = "op_vehicles"
    __table_args__ = (UniqueConstraint("carrier_organization_id", "registration_number"),)
    carrier_organization_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organizations.id"), index=True
    )
    registration_number: Mapped[str] = mapped_column(String(20))
    vehicle_json: Mapped[dict] = mapped_column(JSON_TYPE)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_routing_profile_revision_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    execution_mode: Mapped[str] = mapped_column(
        String(20), default="PRODUCTION", server_default="PRODUCTION"
    )


class Consignment(Mutable, TradeBase):
    __tablename__ = "op_consignments"
    __table_args__ = (
        UniqueConstraint("trade_id", "id"),
        ForeignKeyConstraint(
            ["trade_id", "source_accepted_revision_id"],
            ["trade_revisions.trade_id", "trade_revisions.id"],
        ),
        CheckConstraint("execution_mode IN ('PRODUCTION','SIMULATION')"),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True)
    source_accepted_revision_id: Mapped[str] = mapped_column(ID)
    coordinating_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    execution_mode: Mapped[str] = mapped_column(String(20))
    planning_status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    movement_status: Mapped[str] = mapped_column(String(30), default="NOT_STARTED", index=True)
    revision_alignment: Mapped[str] = mapped_column(String(30), default="CURRENT")
    phase4_legacy_movement: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    plan_json: Mapped[dict] = mapped_column(JSON_TYPE)
    pickup_address_snapshot: Mapped[dict] = mapped_column(JSON_TYPE)
    delivery_address_snapshot: Mapped[dict] = mapped_column(JSON_TYPE)
    active_assignment_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    current_delivery_closure_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    latest_location_json: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    latest_eta_json: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)


class ConsignmentItem(Record, TradeBase):
    __tablename__ = "op_consignment_items"
    __table_args__ = (
        UniqueConstraint("consignment_id", "line_ref"),
        CheckConstraint("allocated_quantity > 0"),
    )
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    line_ref: Mapped[str] = mapped_column(ID, index=True)
    source_trade_item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("trade_item_revisions.id")
    )
    allocated_quantity: Mapped[Decimal] = mapped_column(Q)
    uqc: Mapped[str] = mapped_column(String(10))
    description_snapshot: Mapped[str] = mapped_column(Text)
    specification_snapshot: Mapped[str] = mapped_column(Text)
    cargo_declarations_snapshot: Mapped[dict] = mapped_column(JSON_TYPE)
    loaded_quantity: Mapped[Decimal | None] = mapped_column(Q, nullable=True)


class Assignment(Mutable, TradeBase):
    __tablename__ = "op_transport_assignments"
    __table_args__ = (
        UniqueConstraint("consignment_id", "id"),
        Index(
            "uq_op_accepted_assignment",
            "consignment_id",
            unique=True,
            postgresql_where=text("status = 'ACCEPTED'"),
            sqlite_where=text("status = 'ACCEPTED'"),
        ),
    )
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    carrier_organization_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organizations.id"), index=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("op_vehicles.id"), nullable=True)
    driver_user_id: Mapped[str | None] = mapped_column(ForeignKey("trade_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED")
    booking_start_at: Mapped[datetime] = mapped_column(TS)
    booking_end_at: Mapped[datetime] = mapped_column(TS)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_snapshot: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    driver_snapshot: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    suitability_json: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    proposed_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    supersedes_assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_transport_assignments.id"), nullable=True
    )


class Booking(Record, TradeBase):
    __tablename__ = "op_transport_resource_bookings"
    __table_args__ = (
        Index("ix_op_resource_booking", "resource_type", "resource_id", "released_at"),
    )
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    resource_type: Mapped[str] = mapped_column(String(10))
    resource_id: Mapped[str] = mapped_column(ID)
    booking_start_at: Mapped[datetime] = mapped_column(TS)
    booking_end_at: Mapped[datetime] = mapped_column(TS)
    released_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Event(Record, TradeBase):
    __tablename__ = "op_shipment_events"
    __table_args__ = (
        UniqueConstraint("consignment_id", "client_event_id"),
        ForeignKeyConstraint(
            ["consignment_id", "assignment_id"],
            ["op_transport_assignments.consignment_id", "op_transport_assignments.id"],
        ),
    )
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ID)
    client_event_id: Mapped[str] = mapped_column(ID)
    request_hash: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(TS)
    recorded_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    recorded_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    source: Mapped[str] = mapped_column(String(10), default="WEB")
    latitude: Mapped[Decimal | None] = mapped_column(Q, nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Q, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON_TYPE)
    projection_applied: Mapped[bool] = mapped_column(Boolean, default=True)
    execution_mode: Mapped[str] = mapped_column(String(20))


class Receipt(Record, TradeBase):
    __tablename__ = "op_receipts"
    __table_args__ = (UniqueConstraint("consignment_id", "client_receipt_id"),)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    client_receipt_id: Mapped[str] = mapped_column(ID)
    request_hash: Mapped[str] = mapped_column(String(64))
    receipt_chain_id: Mapped[str] = mapped_column(ID)
    supersedes_receipt_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_receipts.id"), nullable=True, unique=True
    )
    received_at: Mapped[datetime] = mapped_column(TS)
    received_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    receiving_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    receipt_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ReceiptHead(Mutable, TradeBase):
    __tablename__ = "op_receipt_heads"
    receipt_chain_id: Mapped[str] = mapped_column(ID, unique=True)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"))
    effective_receipt_id: Mapped[str] = mapped_column(ForeignKey("op_receipts.id"), unique=True)


class ReceiptLine(Record, TradeBase):
    __tablename__ = "op_receipt_lines"
    __table_args__ = (
        UniqueConstraint("receipt_id", "consignment_item_id"),
        CheckConstraint("delivered_quantity > 0"),
    )
    receipt_id: Mapped[str] = mapped_column(ForeignKey("op_receipts.id"), index=True)
    consignment_item_id: Mapped[str] = mapped_column(ForeignKey("op_consignment_items.id"))
    delivered_quantity: Mapped[Decimal] = mapped_column(Q)
    uqc: Mapped[str] = mapped_column(String(10))
    observed_condition: Mapped[str] = mapped_column(String(30))
    condition_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Inspection(Record, TradeBase):
    __tablename__ = "op_inspection_decisions"
    __table_args__ = (
        CheckConstraint(
            "accepted_quantity >= 0 AND rejected_quantity >= 0 "
            "AND accepted_quantity + rejected_quantity > 0"
        ),
    )
    receipt_line_id: Mapped[str] = mapped_column(ForeignKey("op_receipt_lines.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(10))
    accepted_quantity: Mapped[Decimal] = mapped_column(Q)
    rejected_quantity: Mapped[Decimal] = mapped_column(Q)
    rejection_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reverses_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_inspection_decisions.id"), nullable=True, unique=True
    )
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Closure(Record, TradeBase):
    __tablename__ = "op_delivery_closures"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"))
    closed_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity_summary_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Reopening(Record, TradeBase):
    __tablename__ = "op_delivery_closure_reopenings"
    closure_id: Mapped[str] = mapped_column(ForeignKey("op_delivery_closures.id"), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Dispute(Mutable, TradeBase):
    __tablename__ = "op_disputes"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    consignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_consignments.id"), nullable=True
    )
    receipt_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_receipt_lines.id"), nullable=True
    )
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("op_payments.id"), nullable=True)
    dispute_json: Mapped[dict] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    opened_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    active_proposal_id: Mapped[str | None] = mapped_column(ID, nullable=True)


class DisputeEvent(Record, TradeBase):
    __tablename__ = "op_dispute_events"
    __table_args__ = (UniqueConstraint("proposal_id", "actor_organization_id"),)
    dispute_id: Mapped[str] = mapped_column(ForeignKey("op_disputes.id"))
    event_type: Mapped[str] = mapped_column(String(30))
    proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_dispute_events.id"), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Schedule(Record, TradeBase):
    __tablename__ = "op_payment_schedules"
    __table_args__ = (
        UniqueConstraint("trade_id", "schedule_number"),
        Index(
            "uq_op_active_schedule",
            "trade_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    accepted_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    schedule_number: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(40))
    quoted_goods_total_minor: Mapped[int] = mapped_column(BigInteger)
    due_timezone: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    created_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Obligation(Record, TradeBase):
    __tablename__ = "op_payment_obligations"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    payer_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    payee_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    currency: Mapped[str] = mapped_column(String(3), default="INR")


class ScheduleLine(Record, TradeBase):
    __tablename__ = "op_payment_schedule_lines"
    __table_args__ = (
        UniqueConstraint("schedule_id", "obligation_ref"),
        UniqueConstraint("schedule_id", "line_order"),
        CheckConstraint("face_amount_minor >= 0"),
    )
    schedule_id: Mapped[str] = mapped_column(ForeignKey("op_payment_schedules.id"))
    obligation_ref: Mapped[str] = mapped_column(ForeignKey("op_payment_obligations.id"))
    label: Mapped[str] = mapped_column(Text)
    face_amount_minor: Mapped[int] = mapped_column(BigInteger)
    trigger: Mapped[str] = mapped_column(String(30))
    offset_days: Mapped[int] = mapped_column(Integer)
    fixed_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    line_order: Mapped[int] = mapped_column(Integer)


class ScheduleApproval(Record, TradeBase):
    __tablename__ = "op_payment_schedule_approvals"
    __table_args__ = (UniqueConstraint("schedule_id", "organization_id"),)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("op_payment_schedules.id"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    decision: Mapped[str] = mapped_column(String(10))
    content_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TriggerEvent(Record, TradeBase):
    __tablename__ = "op_payment_trigger_events"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    accepted_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    trigger: Mapped[str] = mapped_column(String(30))
    event_kind: Mapped[str] = mapped_column(String(10))
    occurred_at: Mapped[datetime] = mapped_column(TS)
    source_references_json: Mapped[dict] = mapped_column(JSON_TYPE)
    retracts_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_payment_trigger_events.id"), nullable=True, unique=True
    )


class Payment(Record, TradeBase):
    __tablename__ = "op_payments"
    __table_args__ = (CheckConstraint("amount_minor > 0"),)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    payer_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    payee_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20))
    declared_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    reported_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class PaymentDecision(Record, TradeBase):
    __tablename__ = "op_payment_decisions"
    __table_args__ = (UniqueConstraint("void_request_id", "actor_organization_id"),)
    payment_id: Mapped[str] = mapped_column(ForeignKey("op_payments.id"))
    decision: Mapped[str] = mapped_column(String(30))
    void_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_payment_decisions.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class PaymentAllocation(Record, TradeBase):
    __tablename__ = "op_payment_allocations"
    __table_args__ = (CheckConstraint("amount_minor > 0"),)
    payment_id: Mapped[str] = mapped_column(ForeignKey("op_payments.id"), index=True)
    obligation_ref: Mapped[str] = mapped_column(ForeignKey("op_payment_obligations.id"), index=True)
    basis_schedule_line_id: Mapped[str] = mapped_column(ForeignKey("op_payment_schedule_lines.id"))
    entry_type: Mapped[str] = mapped_column(String(10))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    reverses_allocation_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_payment_allocations.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Attachment(Mutable, TradeBase):
    __tablename__ = "op_operational_attachments"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    consignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_consignments.id"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(20))
    original_name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    security_state: Mapped[str] = mapped_column(String(20), default="UPLOADING")
    verification_status: Mapped[str] = mapped_column(String(20), default="NOT_ASSESSED")
    uploaded_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    finalised_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class AttachmentLink(Record, TradeBase):
    __tablename__ = "op_operational_attachment_links"
    __table_args__ = (UniqueConstraint("attachment_id", "subject_type", "subject_id"),)
    attachment_id: Mapped[str] = mapped_column(ForeignKey("op_operational_attachments.id"))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(ID)
    linked_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


IMMUTABLE_TABLES = [
    model.__tablename__
    for model in (
        Event,
        Receipt,
        ReceiptLine,
        Inspection,
        Closure,
        Reopening,
        DisputeEvent,
        ScheduleLine,
        ScheduleApproval,
        TriggerEvent,
        Obligation,
        Payment,
        PaymentDecision,
        PaymentAllocation,
        AttachmentLink,
    )
]
