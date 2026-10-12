"""Additive evidence ledgers sharing the commercial database and attachment identities."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
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

ID = Uuid(as_uuid=False)
TS = DateTime(timezone=True)


class Document(Mutable, TradeBase):
    __tablename__ = "doc_documents"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    owner_organization_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organizations.id"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(150))
    declared_document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    declared_issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    declared_issuer_organization_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="OWNER_ONLY")
    execution_mode: Mapped[str] = mapped_column(String(20))
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    current_version_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    latest_draft_fact_revision_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    effective_fact_revision_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    current_mapping_revision_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    canonical_document_id: Mapped[str | None] = mapped_column(ID, nullable=True)


class Version(Record, TradeBase):
    __tablename__ = "doc_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("doc_documents.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40))
    reason_text: Mapped[str] = mapped_column(Text)
    supersedes_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_document_versions.id"), nullable=True
    )
    source_manifest_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    created_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Asset(Record, TradeBase):
    __tablename__ = "doc_version_assets"
    __table_args__ = (
        UniqueConstraint("document_version_id", "attachment_id", "role"),
        Index(
            "doc_version_one_primary",
            "document_version_id",
            unique=True,
            postgresql_where=text("role = 'PRIMARY'"),
            sqlite_where=text("role = 'PRIMARY'"),
        ),
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    attachment_id: Mapped[str] = mapped_column(ForeignKey("op_operational_attachments.id"))
    role: Mapped[str] = mapped_column(String(30))
    asset_sha256: Mapped[str] = mapped_column(String(64))


class Relationship(Record, TradeBase):
    __tablename__ = "doc_relationships"
    from_document_id: Mapped[str] = mapped_column(ForeignKey("doc_documents.id"), index=True)
    to_document_id: Mapped[str] = mapped_column(ForeignKey("doc_documents.id"))
    relationship_type: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class SubjectLink(Record, TradeBase):
    __tablename__ = "doc_subject_links"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(ID)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class AccessGrant(Record, TradeBase):
    __tablename__ = "doc_access_grants"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    grantee_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    access_type: Mapped[str] = mapped_column(String(30))
    assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_transport_assignments.id"), nullable=True
    )
    allowed_field_paths_json: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    granted_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Job(Mutable, TradeBase):
    __tablename__ = "doc_processing_jobs"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    stage: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    pipeline_version: Mapped[str] = mapped_column(String(50))
    schema_version: Mapped[str] = mapped_column(String(50))
    configuration_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reprocessing_nonce: Mapped[str | None] = mapped_column(ID, nullable=True)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    requested_by_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    request_json: Mapped[dict] = mapped_column(JSON_TYPE)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    current_attempt_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TS, nullable=True, index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Attempt(Record, TradeBase):
    __tablename__ = "doc_job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_number"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("doc_processing_jobs.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    worker_reference: Mapped[str] = mapped_column(String(100))
    lease_token: Mapped[str] = mapped_column(String(80))
    heartbeat_at: Mapped[datetime] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    redacted_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Outbox(Record, TradeBase):
    __tablename__ = "doc_job_outbox"
    job_id: Mapped[str] = mapped_column(ForeignKey("doc_processing_jobs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30), default="PROCESS_DOCUMENT")
    published_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)


class Artifact(Record, TradeBase):
    __tablename__ = "doc_derived_artifacts"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    source_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_operational_attachments.id"), nullable=True
    )
    job_attempt_id: Mapped[str] = mapped_column(ForeignKey("doc_job_attempts.id"))
    artifact_type: Mapped[str] = mapped_column(String(40))
    object_key: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    transformation_metadata_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Page(Record, TradeBase):
    __tablename__ = "doc_pages"
    __table_args__ = (
        UniqueConstraint("document_version_id", "page_number", "page_image_artifact_id"),
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    page_image_artifact_id: Mapped[str] = mapped_column(ForeignKey("doc_derived_artifacts.id"))
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    transformation_json: Mapped[dict] = mapped_column(JSON_TYPE)


class FileMetadata(Record, TradeBase):
    __tablename__ = "doc_file_metadata"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    attachment_id: Mapped[str] = mapped_column(ForeignKey("op_operational_attachments.id"))
    job_attempt_id: Mapped[str] = mapped_column(ForeignKey("doc_job_attempts.id"))
    metadata_schema_version: Mapped[str] = mapped_column(String(50), default="PH3_FILE_V1")
    metadata_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Extraction(Record, TradeBase):
    __tablename__ = "doc_extraction_runs"
    proposed_document_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    job_attempt_id: Mapped[str] = mapped_column(ForeignKey("doc_job_attempts.id"), unique=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    source_manifest_hash: Mapped[str] = mapped_column(String(64))
    engine_kind: Mapped[str] = mapped_column(String(30))
    engine_name: Mapped[str] = mapped_column(String(80))
    engine_version: Mapped[str] = mapped_column(String(50))
    schema_version: Mapped[str] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    raw_result_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_derived_artifacts.id"), nullable=True
    )
    finished_at: Mapped[datetime] = mapped_column(TS)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Observation(Record, TradeBase):
    __tablename__ = "doc_field_observations"
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("doc_extraction_runs.id"), index=True)
    field_path: Mapped[str] = mapped_column(String(500))
    row_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalised_value_json: Mapped[object | None] = mapped_column(JSON_TYPE, nullable=True)
    value_type: Mapped[str] = mapped_column(String(20))
    extraction_method: Mapped[str] = mapped_column(String(30))
    provider_confidence: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20))
    source_locator_json: Mapped[dict] = mapped_column(JSON_TYPE)
    normalisation_warnings_json: Mapped[list] = mapped_column(JSON_TYPE, default=list)


class FactRevision(Record, TradeBase):
    __tablename__ = "doc_fact_revisions"
    __table_args__ = (UniqueConstraint("document_version_id", "revision_number"),)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    base_fact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_fact_revisions.id"), nullable=True
    )
    extraction_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_extraction_runs.id"), nullable=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    canonical_document_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_users.id"), nullable=True
    )
    created_by_organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_organizations.id"), nullable=True
    )


class FieldDecision(Record, TradeBase):
    __tablename__ = "doc_field_decisions"
    __table_args__ = (UniqueConstraint("fact_revision_id", "field_path"),)
    fact_revision_id: Mapped[str] = mapped_column(ForeignKey("doc_fact_revisions.id"), index=True)
    field_path: Mapped[str] = mapped_column(String(500))
    document_line_ref: Mapped[str | None] = mapped_column(ID, nullable=True)
    observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_field_observations.id"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(30))
    effective_value_json: Mapped[object | None] = mapped_column(JSON_TYPE, nullable=True)
    provenance: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_locator_json: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)


class LineIdentity(Record, TradeBase):
    __tablename__ = "doc_line_identities"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    issued_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_users.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(200))
    source_row_key: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ReviewedLine(Record, TradeBase):
    __tablename__ = "doc_reviewed_lines"
    __table_args__ = (
        UniqueConstraint("fact_revision_id", "document_line_ref"),
        UniqueConstraint("fact_revision_id", "line_order"),
    )
    fact_revision_id: Mapped[str] = mapped_column(ForeignKey("doc_fact_revisions.id"), index=True)
    document_line_ref: Mapped[str] = mapped_column(ID)
    line_order: Mapped[int] = mapped_column(Integer)
    line_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ReviewDecision(Record, TradeBase):
    __tablename__ = "doc_review_decisions"
    fact_revision_id: Mapped[str] = mapped_column(ForeignKey("doc_fact_revisions.id"), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    review_state: Mapped[str] = mapped_column(String(50))
    content_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class MappingRevision(Record, TradeBase):
    __tablename__ = "doc_mapping_revisions"
    document_id: Mapped[str] = mapped_column(ForeignKey("doc_documents.id"), index=True)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("doc_document_versions.id"))
    fact_revision_id: Mapped[str] = mapped_column(ForeignKey("doc_fact_revisions.id"))
    accepted_trade_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    base_mapping_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_mapping_revisions.id"), nullable=True
    )
    source_context_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class LineMapping(Record, TradeBase):
    __tablename__ = "doc_line_mappings"
    mapping_revision_id: Mapped[str] = mapped_column(
        ForeignKey("doc_mapping_revisions.id"), index=True
    )
    document_line_ref: Mapped[str] = mapped_column(ID)
    trade_line_ref: Mapped[str] = mapped_column(ID)
    target_kind: Mapped[str] = mapped_column(String(30))
    consignment_item_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    target_snapshot_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    mapped_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    uqc: Mapped[str] = mapped_column(String(10))
    mapping_method: Mapped[str] = mapped_column(String(30), default="HUMAN_CONFIRMED")


class Assessment(Record, TradeBase):
    __tablename__ = "doc_assessment_runs"
    job_attempt_id: Mapped[str] = mapped_column(ForeignKey("doc_job_attempts.id"), unique=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    fact_revision_id: Mapped[str] = mapped_column(ForeignKey("doc_fact_revisions.id"))
    mapping_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_mapping_revisions.id"), nullable=True
    )
    accepted_trade_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_revisions.id"), nullable=True
    )
    assessment_stage: Mapped[str] = mapped_column(String(30))
    check_pack_version: Mapped[str] = mapped_column(String(50))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    source_context_json: Mapped[dict] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(20))


class Finding(Record, TradeBase):
    __tablename__ = "doc_assessment_findings"
    assessment_run_id: Mapped[str] = mapped_column(ForeignKey("doc_assessment_runs.id"), index=True)
    check_code: Mapped[str] = mapped_column(String(80))
    check_version: Mapped[str] = mapped_column(String(50))
    dimension: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(20))
    expected_source_json: Mapped[dict] = mapped_column(JSON_TYPE)
    observed_source_json: Mapped[dict] = mapped_column(JSON_TYPE)
    expected_value_json: Mapped[object | None] = mapped_column(JSON_TYPE, nullable=True)
    observed_value_json: Mapped[object | None] = mapped_column(JSON_TYPE, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    limitations_json: Mapped[list] = mapped_column(JSON_TYPE, default=list)


class FindingAnnotation(Record, TradeBase):
    __tablename__ = "doc_finding_annotations"
    finding_id: Mapped[str] = mapped_column(ForeignKey("doc_assessment_findings.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    related_new_assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_assessment_runs.id"), nullable=True
    )
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Connection(Mutable, TradeBase):
    __tablename__ = "doc_verification_connections"
    organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"), index=True)
    adapter_name: Mapped[str] = mapped_column(String(80))
    adapter_version: Mapped[str] = mapped_column(String(50))
    provider_environment: Mapped[str] = mapped_column(String(20))
    requester_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    secret_reference: Mapped[str] = mapped_column(String(100))
    allowed_check_types_json: Mapped[list] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(30), default="CONFIGURED")


class TrustedKey(Record, TradeBase):
    __tablename__ = "doc_trusted_verification_keys"
    issuer: Mapped[str] = mapped_column(String(200))
    key_purpose: Mapped[str] = mapped_column(String(40))
    provider_environment: Mapped[str] = mapped_column(String(20))
    key_identifier: Mapped[str] = mapped_column(String(100), unique=True)
    key_fingerprint: Mapped[str] = mapped_column(String(64))
    algorithm: Mapped[str] = mapped_column(String(20))
    public_key_reference: Mapped[str] = mapped_column(Text)
    official_source_url: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    historical_validity_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    registry_policy_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class VerificationCheck(Record, TradeBase):
    __tablename__ = "doc_verification_checks"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    fact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_fact_revisions.id"), nullable=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    check_type: Mapped[str] = mapped_column(String(40))
    target_field_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_payload_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_derived_artifacts.id"), nullable=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_verification_connections.id"), nullable=True
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    request_configuration_json: Mapped[dict] = mapped_column(JSON_TYPE)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class VerificationResult(Record, TradeBase):
    __tablename__ = "doc_verification_results"
    verification_check_id: Mapped[str] = mapped_column(
        ForeignKey("doc_verification_checks.id"), index=True
    )
    job_attempt_id: Mapped[str] = mapped_column(ForeignKey("doc_job_attempts.id"))
    result_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ManualAttestation(Record, TradeBase):
    __tablename__ = "doc_manual_attestations"
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_document_versions.id"), index=True
    )
    fact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("doc_fact_revisions.id"), nullable=True
    )
    check_type: Mapped[str] = mapped_column(String(40))
    target_identifier: Mapped[str] = mapped_column(String(100))
    portal_source_url: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(TS)
    observed_status: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organization_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


IMMUTABLE_TABLES = [
    model.__tablename__
    for model in (
        Version,
        Asset,
        Relationship,
        Artifact,
        Page,
        FileMetadata,
        Extraction,
        Observation,
        FactRevision,
        FieldDecision,
        ReviewedLine,
        LineIdentity,
        ReviewDecision,
        MappingRevision,
        LineMapping,
        Assessment,
        Finding,
        FindingAnnotation,
        TrustedKey,
        VerificationCheck,
        VerificationResult,
        ManualAttestation,
    )
]
