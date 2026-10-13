from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.trades.models import now

from .model_base import JSON_TYPE, TS, Authored, Snapshot, TradeBase


class TradeContext(TradeBase):
    __tablename__ = "trade_compliance_contexts"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), primary_key=True)
    context_version: Mapped[int] = mapped_column(BigInteger, default=0)
    last_changed_at: Mapped[datetime] = mapped_column(TS, default=now)
    last_change_code: Mapped[str] = mapped_column(String(100), default="INITIAL")


class Heads(TradeBase):
    __tablename__ = "consignment_compliance_heads"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), primary_key=True)
    current_fact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("compliance_fact_revisions.id"), nullable=True
    )
    current_binding_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("consignment_evidence_binding_revisions.id"), nullable=True
    )
    current_loading_manifest_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("loading_manifest_revisions.id"), nullable=True
    )
    current_pickup_evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("compliance_evaluations.id"), nullable=True
    )
    current_departure_evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("compliance_evaluations.id"), nullable=True
    )
    pickup_authorization_id: Mapped[str | None] = mapped_column(
        ForeignKey("dispatch_authorizations.id"), nullable=True
    )
    departure_authorization_id: Mapped[str | None] = mapped_column(
        ForeignKey("dispatch_authorizations.id"), nullable=True
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class Fact(Snapshot, TradeBase):
    __tablename__ = "compliance_fact_revisions"
    __table_args__ = (UniqueConstraint("consignment_id", "revision_number"),)
    revision_number: Mapped[int] = mapped_column(Integer)
    accepted_trade_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_transport_assignments.id"), nullable=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    prepared_context_version: Mapped[int] = mapped_column(BigInteger)
    inherited_hash: Mapped[str] = mapped_column(String(64))
    submitted_for_review: Mapped[bool] = mapped_column(Boolean)
    facts_json: Mapped[dict] = mapped_column(JSON_TYPE)
    provenance_json: Mapped[dict] = mapped_column(JSON_TYPE)


class FactReview(Authored, TradeBase):
    __tablename__ = "compliance_fact_reviews"
    fact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("compliance_fact_revisions.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)


class PrivateIdentity(Authored, TradeBase):
    __tablename__ = "compliance_private_identities"
    seller_organisation_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organizations.id"), index=True
    )
    encrypted_identity_json: Mapped[dict] = mapped_column(JSON_TYPE)
    identity_hash: Mapped[str] = mapped_column(String(64))


class Turnover(Authored, TradeBase):
    __tablename__ = "pan_turnover_declarations"
    seller_organisation_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organizations.id"), index=True
    )
    pan_identity_reference: Mapped[str] = mapped_column(
        ForeignKey("compliance_private_identities.id")
    )
    assessment_invoice_date: Mapped[str] = mapped_column(String(10))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    declaration_json: Mapped[dict] = mapped_column(JSON_TYPE)
    source_document_version_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    source_basis_manifest_json: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    derived_context_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


class TurnoverReview(Authored, TradeBase):
    __tablename__ = "pan_turnover_reviews"
    declaration_id: Mapped[str] = mapped_column(
        ForeignKey("pan_turnover_declarations.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)


class Manifest(Snapshot, TradeBase):
    __tablename__ = "loading_manifest_revisions"
    __table_args__ = (UniqueConstraint("consignment_id", "revision_number"),)
    revision_number: Mapped[int] = mapped_column(Integer)
    accepted_trade_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    manifest_json: Mapped[dict] = mapped_column(JSON_TYPE)


class TransportEvidence(Snapshot, TradeBase):
    __tablename__ = "transport_evidence_revisions"
    __table_args__ = (
        Index("ix_transport_evidence_subject", "assignment_id", "subject_id", "evidence_type"),
    )
    owner_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_transport_assignments.id"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[str] = mapped_column(String(36))
    evidence_type: Mapped[str] = mapped_column(String(40))
    document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_document_versions.id"), nullable=True
    )
    reviewed_fact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_fact_revisions.id"), nullable=True
    )
    verification_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_verification_results.id"), nullable=True
    )
    parent_permit_evidence_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("transport_evidence_revisions.id"), nullable=True
    )
    evidence_json: Mapped[dict] = mapped_column(JSON_TYPE)


class TransportReview(Authored, TradeBase):
    __tablename__ = "transport_evidence_reviews"
    evidence_revision_id: Mapped[str] = mapped_column(
        ForeignKey("transport_evidence_revisions.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(40))
    reviewer_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    reason: Mapped[str] = mapped_column(Text)


class Binding(Snapshot, TradeBase):
    __tablename__ = "consignment_evidence_binding_revisions"
    __table_args__ = (UniqueConstraint("consignment_id", "revision_number"),)
    revision_number: Mapped[int] = mapped_column(Integer)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    fact_revision_id: Mapped[str] = mapped_column(ForeignKey("compliance_fact_revisions.id"))
    turnover_declaration_id: Mapped[str | None] = mapped_column(
        ForeignKey("pan_turnover_declarations.id"), nullable=True
    )
    loading_manifest_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("loading_manifest_revisions.id"), nullable=True
    )
    binding_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Reservation(Snapshot, TradeBase):
    __tablename__ = "movement_document_reservations"
    __table_args__ = (
        Index(
            "uq_active_movement_invoice",
            "issuer_organisation_id",
            "issuer_document_identity_hash",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
            sqlite_where=text("released_at IS NULL"),
        ),
    )
    issuer_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    issuer_document_identity_hash: Mapped[str] = mapped_column(String(64))
    canonical_document_id: Mapped[str] = mapped_column(ForeignKey("doc_documents.id"))
    released_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    first_consumed_movement_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_shipment_events.id"), nullable=True
    )


class ReservationEvent(Authored, TradeBase):
    __tablename__ = "movement_document_reservation_events"
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey("movement_document_reservations.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(20))
    movement_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_shipment_events.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text)
