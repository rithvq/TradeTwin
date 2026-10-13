from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .model_base import JSON_TYPE, TS, Authored, ConsignmentRecord, TradeBase


class Packet(ConsignmentRecord, TradeBase):
    __tablename__ = "dispatch_packets"
    action: Mapped[str] = mapped_column(String(30))
    execution_mode: Mapped[str] = mapped_column(String(20))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    prepared_by_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    approval_id: Mapped[str] = mapped_column(ForeignKey("compliance_review_decisions.id"))
    loading_manifest_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("loading_manifest_revisions.id"), nullable=True
    )
    dependency_hash: Mapped[str] = mapped_column(String(64))
    packet_hash: Mapped[str] = mapped_column(String(64))
    valid_until: Mapped[datetime] = mapped_column(TS)
    manifest_json: Mapped[dict] = mapped_column(JSON_TYPE)


class PacketItem(Authored, TradeBase):
    __tablename__ = "dispatch_packet_items"
    packet_id: Mapped[str] = mapped_column(ForeignKey("dispatch_packets.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("compliance_requirements.id"))
    document_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_document_versions.id"), nullable=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_derived_artifacts.id"), nullable=True
    )
    representation_type: Mapped[str] = mapped_column(String(40))
    carry_method: Mapped[str] = mapped_column(String(40))
    allowed_recipient_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    sensitivity_class: Mapped[str] = mapped_column(String(40))
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    limitations_json: Mapped[list] = mapped_column(JSON_TYPE)
    source_reference_json: Mapped[dict] = mapped_column(JSON_TYPE)


class PacketAck(Authored, TradeBase):
    __tablename__ = "dispatch_packet_acknowledgments"
    __table_args__ = (CheckConstraint("possession_confirmed = true"),)
    packet_id: Mapped[str] = mapped_column(ForeignKey("dispatch_packets.id"), index=True)
    packet_hash: Mapped[str] = mapped_column(String(64))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    possession_confirmed: Mapped[bool] = mapped_column(Boolean)
    carry_methods_json: Mapped[list] = mapped_column(JSON_TYPE)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Authorization(ConsignmentRecord, TradeBase):
    __tablename__ = "dispatch_authorizations"
    __table_args__ = (Index("ix_authorization_action", "consignment_id", "action", "issued_at"),)
    action: Mapped[str] = mapped_column(String(30))
    issued_by_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    execution_mode: Mapped[str] = mapped_column(String(20))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    expected_movement_status: Mapped[str] = mapped_column(String(30))
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("compliance_evaluations.id"))
    evaluation_hash: Mapped[str] = mapped_column(String(64))
    dependency_hash: Mapped[str] = mapped_column(String(64))
    context_version: Mapped[int] = mapped_column(BigInteger)
    registry_epoch_manifest: Mapped[dict] = mapped_column(JSON_TYPE)
    approval_id: Mapped[str] = mapped_column(ForeignKey("compliance_review_decisions.id"))
    packet_id: Mapped[str] = mapped_column(ForeignKey("dispatch_packets.id"))
    packet_hash: Mapped[str] = mapped_column(String(64))
    acknowledgment_id: Mapped[str] = mapped_column(ForeignKey("dispatch_packet_acknowledgments.id"))
    loading_manifest_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("loading_manifest_revisions.id"), nullable=True
    )
    issued_at: Mapped[datetime] = mapped_column(TS)
    valid_from: Mapped[datetime] = mapped_column(TS)
    expires_at: Mapped[datetime] = mapped_column(TS)
    consumed_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_shipment_events.id"), nullable=True, unique=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuthorizationEvent(Authored, TradeBase):
    __tablename__ = "dispatch_authorization_events"
    authorisation_id: Mapped[str] = mapped_column(
        ForeignKey("dispatch_authorizations.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(20))
    movement_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_shipment_events.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
