"""Separate commercial ledger metadata: sharing is explicit, not profile-owner based."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid4())


class TradeBase(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Mutable(Record):
    created_by: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class User(Mutable, TradeBase):
    __tablename__ = "trade_users"
    identity_subject: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    phone_e164: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Organization(Mutable, TradeBase):
    __tablename__ = "trade_organizations"
    legal_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorised_contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    mobile_e164: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_address: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    registration_position: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_status: Mapped[str] = mapped_column(String(20), default="DRAFT")


class Membership(Mutable, TradeBase):
    __tablename__ = "trade_organization_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class Grant(Mutable, TradeBase):
    __tablename__ = "trade_permission_grants"
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organization_memberships.id"), index=True
    )
    capability: Mapped[str] = mapped_column(String(40))
    permission_code: Mapped[str] = mapped_column(String(60))
    trade_id: Mapped[str | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Registration(Mutable, TradeBase):
    __tablename__ = "trade_gst_registrations"
    __table_args__ = (UniqueConstraint("id", "organization_id"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), index=True)
    gstin: Mapped[str] = mapped_column(String(15), unique=True)
    state_code: Mapped[str] = mapped_column(String(2))
    declared_taxpayer_scheme: Mapped[str] = mapped_column(String(20))
    declared_establishment_kind: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40), default="SELF_DECLARED")
    verification_status: Mapped[str] = mapped_column(String(40), default="FORMAT_VALIDATED")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    existing_verification_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class Location(Mutable, TradeBase):
    __tablename__ = "trade_locations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["registration_id", "organization_id"],
            ["trade_gst_registrations.id", "trade_gst_registrations.organization_id"],
        ),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), index=True)
    registration_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    label: Mapped[str] = mapped_column(Text)
    location_type: Mapped[str] = mapped_column(String(20))
    address: Mapped[dict] = mapped_column(JSON_TYPE)
    visibility: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Trade(Mutable, TradeBase):
    __tablename__ = "trades"
    __table_args__ = tuple(
        ForeignKeyConstraint(
            ["id", column],
            [f"{target}.trade_id", f"{target}.id"],
            name=f"fk_trade_{column}",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        )
        for column, target in (
            ("current_revision_id", "trade_revisions"),
            ("accepted_revision_id", "trade_revisions"),
            ("active_offer_id", "trade_offers"),
            ("pending_amendment_id", "trade_amendments"),
        )
    )
    reference: Mapped[str] = mapped_column(String(100), unique=True)
    creator_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    initiated_by_role: Mapped[str] = mapped_column(String(10))
    agreement_status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    current_revision_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    accepted_revision_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    active_offer_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    pending_amendment_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    execution_mode: Mapped[str] = mapped_column(
        String(20), default="PRODUCTION", server_default="PRODUCTION"
    )
    active_payment_schedule_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), nullable=True
    )
    payment_schedule_review_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )


class Participant(Record, TradeBase):
    __tablename__ = "trade_participants"
    __table_args__ = (
        UniqueConstraint("trade_id", "participant_role"),
        UniqueConstraint("trade_id", "organization_id"),
        UniqueConstraint("trade_id", "participant_role", "organization_id"),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), index=True)
    participant_role: Mapped[str] = mapped_column(String(10))


class Snapshot(Record, TradeBase):
    __tablename__ = "trade_party_snapshots"
    __table_args__ = (
        UniqueConstraint("trade_id", "id"),
        UniqueConstraint("trade_id", "id", "participant_role", "organization_id"),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    participant_role: Mapped[str] = mapped_column(String(10))
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    snapshot_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


class Revision(Record, TradeBase):
    __tablename__ = "trade_revisions"
    __table_args__ = (
        UniqueConstraint("trade_id", "revision_number"),
        UniqueConstraint("trade_id", "id"),
        ForeignKeyConstraint(
            ["trade_id", "seller_snapshot_id"],
            ["trade_party_snapshots.trade_id", "trade_party_snapshots.id"],
        ),
        ForeignKeyConstraint(
            ["trade_id", "buyer_snapshot_id"],
            ["trade_party_snapshots.trade_id", "trade_party_snapshots.id"],
        ),
        ForeignKeyConstraint(
            ["trade_id", "supersedes_revision_id"],
            ["trade_revisions.trade_id", "trade_revisions.id"],
        ),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    revision_kind: Mapped[str] = mapped_column(String(30))
    seller_snapshot_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    buyer_snapshot_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    facts_json: Mapped[dict] = mapped_column(JSON_TYPE)
    pricing_summary_json: Mapped[dict] = mapped_column(JSON_TYPE)
    terms_hash: Mapped[str] = mapped_column(String(64))
    supersedes_revision_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class Item(Record, TradeBase):
    __tablename__ = "trade_item_revisions"
    __table_args__ = (
        UniqueConstraint("trade_revision_id", "line_ref"),
        UniqueConstraint("trade_revision_id", "line_no"),
    )
    trade_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"), index=True)
    line_ref: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    hsn_confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    uqc: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price_minor: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    discount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    declared_tax_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    cargo_declarations_json: Mapped[dict] = mapped_column(JSON_TYPE)
    line_before_discount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    line_quoted_total_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    line_tax_estimate_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Offer(Record, TradeBase):
    __tablename__ = "trade_offers"
    __table_args__ = (
        UniqueConstraint("trade_id", "id"),
        UniqueConstraint("id", "revision_id", "trade_id"),
        ForeignKeyConstraint(
            ["trade_id", "revision_id"], ["trade_revisions.trade_id", "trade_revisions.id"]
        ),
        Index(
            "uq_trade_active_offer",
            "trade_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_trade_offer_expiration", "status", "expires_at"),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    revision_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    purpose: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    published_by: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    published_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Approval(Record, TradeBase):
    __tablename__ = "trade_commercial_approvals"
    __table_args__ = (
        UniqueConstraint("offer_id", "participant_role"),
        ForeignKeyConstraint(
            ["offer_id", "revision_id", "trade_id"],
            ["trade_offers.id", "trade_offers.revision_id", "trade_offers.trade_id"],
        ),
        ForeignKeyConstraint(
            ["trade_id", "party_snapshot_id", "participant_role", "organization_id"],
            [
                "trade_party_snapshots.trade_id",
                "trade_party_snapshots.id",
                "trade_party_snapshots.participant_role",
                "trade_party_snapshots.organization_id",
            ],
        ),
    )
    trade_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    offer_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    revision_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    participant_role: Mapped[str] = mapped_column(String(10))
    organization_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    party_snapshot_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    capability: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(10))
    terms_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    authentication_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class Amendment(Mutable, TradeBase):
    __tablename__ = "trade_amendments"
    __table_args__ = (
        UniqueConstraint("trade_id", "id"),
        ForeignKeyConstraint(
            ["trade_id", "base_accepted_revision_id"],
            ["trade_revisions.trade_id", "trade_revisions.id"],
        ),
        ForeignKeyConstraint(
            ["trade_id", "proposed_revision_id"], ["trade_revisions.trade_id", "trade_revisions.id"]
        ),
        ForeignKeyConstraint(
            ["trade_id", "offer_id"], ["trade_offers.trade_id", "trade_offers.id"]
        ),
        Index(
            "uq_trade_active_amendment",
            "trade_id",
            unique=True,
            postgresql_where=text("status IN ('DRAFT', 'OFFERED')"),
            sqlite_where=text("status IN ('DRAFT', 'OFFERED')"),
        ),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    base_accepted_revision_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    proposed_revision_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    proposer_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    offer_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)


class Audit(Record, TradeBase):
    __tablename__ = "trade_audit_events"
    document_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    __table_args__ = (Index("ix_trade_evidence_time", "trade_id", "created_at", "id"),)
    trade_id: Mapped[str | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_organizations.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(60))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("trade_revisions.id"), nullable=True)
    terms_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    redacted_summary_json: Mapped[dict] = mapped_column(JSON_TYPE)
    consignment_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), nullable=True, index=True
    )
    execution_mode: Mapped[str] = mapped_column(
        String(20), default="PRODUCTION", server_default="PRODUCTION"
    )


class Idempotency(Record, TradeBase):
    __tablename__ = "trade_idempotency_records"
    __table_args__ = (UniqueConstraint("scope_key", "operation", "idempotency_key"),)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_organizations.id"), nullable=True
    )
    scope_key: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body_json: Mapped[dict] = mapped_column(JSON_TYPE)
    response_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
