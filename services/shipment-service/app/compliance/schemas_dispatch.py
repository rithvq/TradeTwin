from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.trades.schemas import Schema

from .schemas_facts import Action, Code, Hash, Ids, Note

Representation = Literal[
    "PAPER_INVOICE_REFERENCE",
    "INVOICE_COPY",
    "SIGNED_IRN_QR",
    "EWB_COPY",
    "EWB_NUMBER",
    "TRANSPORT_RECORD_REFERENCE",
]
CarryMethod = Literal[
    "PAPER_COPY",
    "DIGITAL_OFFLINE_COPY",
    "SIGNED_IRN_QR_ELECTRONIC",
    "EWB_NUMBER_AVAILABLE",
    "ISSUER_APP_RECORD",
]


class Reason(Schema):
    reason: Note


class CaseActionInput(Schema):
    evaluation_id: UUID
    requirement_id: UUID
    action: Literal[
        "FIX_SOURCE",
        "SUPPLY_MISSING_FACT",
        "APPLY_PUBLISHED_EXCEPTION",
        "ACKNOWLEDGE_POLICY_WARNING",
        "REQUEST_RULE_SCOPE_EXTENSION",
        "ADD_COMMENT",
    ]
    reason: Note
    fact_revision_id: UUID | None = None
    document_version_ids: Ids = Field(default_factory=list)
    verification_result_ids: Ids = Field(default_factory=list)
    exception_rule_id: UUID | None = None
    exception_code: Code | None = None
    followup_evaluation_id: UUID | None = None


class ReleaseDecision(Schema):
    decision: Literal["APPROVE_RELEASE", "RETURN_FOR_CORRECTION"]
    evaluation_hash: Hash
    acknowledged_warning_action_ids: Ids = Field(default_factory=list)
    reason: Note


class HoldEvidence(Schema):
    document_version_id: UUID | None = None
    verification_result_id: UUID | None = None
    requirement_id: UUID | None = None
    movement_event_id: UUID | None = None

    @model_validator(mode="after")
    def reference(self):
        if sum(getattr(self, field) is not None for field in type(self).model_fields) != 1:
            raise ValueError("Select exactly one evidence record, never embed its payload")
        return self


class HoldInput(Schema):
    reason_code: Literal[
        "SUSPECTED_TAMPERING",
        "CONTRADICTORY_AUTHORITY_OBSERVATIONS",
        "IDENTITY_MISMATCH",
        "PUBLISHED_INTEGRITY_REASON",
    ]
    reason: Note
    evidence_references: list[HoldEvidence] = Field(default_factory=list, max_length=40)


class HoldRelease(Reason):
    release_request_event_id: UUID


class SelectedRepresentation(Schema):
    requirement_id: UUID
    representation_type: Representation
    source_reference: dict
    carry_method: CarryMethod


class PacketPrepare(Schema):
    action: Action
    evaluation_id: UUID
    evaluation_hash: Hash
    approval_id: UUID
    selected_representations: list[SelectedRepresentation] = Field(min_length=1, max_length=40)


class Acknowledge(Schema):
    packet_hash: Hash
    assignment_id: UUID
    possession_confirmed: Literal[True]
    carry_methods: list[CarryMethod] = Field(min_length=1, max_length=6)
    note: str | None = Field(None, max_length=1000)


class AuthorizationInput(Schema):
    action: Action
    evaluation_id: UUID
    evaluation_hash: Hash
    approval_id: UUID
    packet_id: UUID
    packet_hash: Hash
    acknowledgment_id: UUID
    expected_context_version: int = Field(ge=0)
