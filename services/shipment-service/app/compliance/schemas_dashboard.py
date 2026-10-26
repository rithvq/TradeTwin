"""Bounded public projections; no raw witnesses, document contents or full hashes."""

from typing import Literal
from uuid import UUID

from app.trades.schemas import Schema

from .schemas_facts import Action, Mode
from .schemas_views import ComputationTraceView


class DispatchLink(Schema):
    label: str
    href: str


class DispatchCounts(Schema):
    ready_to_move: int
    awaiting_evidence_or_review: int
    expiring_soon: int
    blocked: int


class DispatchRow(Schema):
    consignment_id: UUID
    reference: str
    trade_id: UUID
    trade_reference: str
    execution_mode: Mode
    movement_status: str
    action: Action
    state: str
    readiness_state: str
    current_stage: str
    reason_codes: list[str]
    expiring_soon: bool
    expires_at: str | None
    checked_at: str
    links: list[DispatchLink]


class DispatchDashboardView(Schema):
    schema_version: Literal["DISPATCH_DASHBOARD_V1"]
    organization_id: UUID
    checked_at: str
    counts: DispatchCounts
    counts_scope: Literal["ALL_AUTHORIZED_CONSIGNMENTS"]
    expiring_within_seconds: int
    total: int
    items: list[DispatchRow]
    next_cursor: UUID | None


class DispatchStageItem(Schema):
    label: str
    status: str
    reason_codes: list[str]
    description: str | None = None


class DispatchStage(Schema):
    number: int
    name: str
    status: str
    facts: dict[str, str | int | bool | None]
    reason_codes: list[str]
    items: list[DispatchStageItem]


class EvidenceTransition(Schema):
    document_type: str
    basis: str
    code: str


class EvidenceChangesView(Schema):
    status: str
    detail_status: str
    reason_codes: list[str]
    transitions: list[EvidenceTransition]
    notice: str


class BindingItem(Schema):
    label: str
    status: str
    reference: str | None
    reason_codes: list[str]


class ExactBindingView(Schema):
    items: list[BindingItem]
    manifest_path: str | None
    notice: str


class WindowInput(Schema):
    code: str
    at: str


class WindowView(Schema):
    detail_status: str
    notice: str
    schema_version: str | None = None
    valid_from: str | None = None
    expires_at: str | None = None
    start_inputs: list[WindowInput] = []
    expiry_inputs: list[WindowInput] = []
    start_limited_by: list[str] = []
    expiry_limited_by: list[str] = []
    evaluation_deadlines: list[WindowInput] = []


class DispatchAlert(Schema):
    code: str
    severity: str


class DispatchJourneyView(Schema):
    schema_version: Literal["DISPATCH_JOURNEY_V1"]
    consignment_id: UUID
    reference: str
    trade_id: UUID
    action: Action
    execution_mode: Mode
    checked_at: str
    readiness_state: str
    historical: bool
    links: list[DispatchLink]
    stages: list[DispatchStage]
    evidence_changes: EvidenceChangesView
    calculation: ComputationTraceView | None
    binding: ExactBindingView
    validity: WindowView
    post_dispatch_alerts: list[DispatchAlert]
