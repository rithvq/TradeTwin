"""Phase 5 retained revisions and mutable lifecycle heads share the commercial ledger."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.trades.models import JSON_TYPE, Mutable, Record, TradeBase

TS = DateTime(timezone=True)


class Snapshot(Record):
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class Location(Snapshot, TradeBase):
    __tablename__ = "routing_location_revisions"
    __table_args__ = (UniqueConstraint("consignment_id", "address_role", "revision_number"),)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    address_role: Mapped[str] = mapped_column(String(10))
    revision_number: Mapped[int] = mapped_column(Integer)
    accepted_address_hash: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    precision: Mapped[str] = mapped_column(String(30))
    state_code: Mapped[str] = mapped_column(String(2))
    location_json: Mapped[dict] = mapped_column(JSON_TYPE)


class LocationHead(Mutable, TradeBase):
    __tablename__ = "consignment_routing_location_heads"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), unique=True)
    pickup_location_revision_id: Mapped[str | None] = mapped_column(ForeignKey(Location.id))
    drop_location_revision_id: Mapped[str | None] = mapped_column(ForeignKey(Location.id))


class Profile(Snapshot, TradeBase):
    __tablename__ = "routing_vehicle_profile_revisions"
    __table_args__ = (UniqueConstraint("vehicle_id", "revision_number"),)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("op_vehicles.id"), index=True)
    carrier_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    revision_number: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[dict] = mapped_column(JSON_TYPE)


class Dataset(Snapshot, TradeBase):
    __tablename__ = "route_dataset_revisions"
    __table_args__ = (UniqueConstraint("dataset_code", "version", "execution_mode"),)
    dataset_code: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(100))
    execution_mode: Mapped[str] = mapped_column(String(20))
    dataset_json: Mapped[dict] = mapped_column(JSON_TYPE)
    valid_from: Mapped[datetime] = mapped_column(TS)
    valid_until: Mapped[datetime | None] = mapped_column(TS)


class DatasetEvent(Record, TradeBase):
    __tablename__ = "route_dataset_publication_events"
    dataset_revision_id: Mapped[str] = mapped_column(ForeignKey(Dataset.id), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class Template(Snapshot, TradeBase):
    __tablename__ = "route_template_revisions"
    __table_args__ = (UniqueConstraint("template_code", "revision_number"),)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    template_code: Mapped[str] = mapped_column(String(120))
    revision_number: Mapped[int] = mapped_column(Integer)
    dataset_revision_id: Mapped[str] = mapped_column(ForeignKey(Dataset.id))
    template_json: Mapped[dict] = mapped_column(JSON_TYPE)


class RFQ(Mutable, TradeBase):
    __tablename__ = "freight_rfqs"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    requesting_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    freight_payer_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    accepted_trade_revision_id: Mapped[str] = mapped_column(ForeignKey("trade_revisions.id"))
    request_json: Mapped[dict] = mapped_column(JSON_TYPE)
    context_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    execution_mode: Mapped[str] = mapped_column(String(20))
    response_deadline: Mapped[datetime] = mapped_column(TS, index=True)
    lifecycle_projection: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    supersedes_rfq_id: Mapped[str | None] = mapped_column(ForeignKey("freight_rfqs.id"))


class Invitation(Record, TradeBase):
    __tablename__ = "freight_rfq_invitations"
    __table_args__ = (UniqueConstraint("rfq_id", "carrier_organisation_id"),)
    rfq_id: Mapped[str] = mapped_column(ForeignKey(RFQ.id))
    carrier_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class QuoteHead(Mutable, TradeBase):
    __tablename__ = "freight_quote_heads"
    rfq_id: Mapped[str] = mapped_column(ForeignKey(RFQ.id), index=True)
    carrier_organisation_id: Mapped[str] = mapped_column(
        ForeignKey("trade_organizations.id"), index=True
    )
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "freight_quote_revisions.id", use_alter=True, name="fk_freight_quote_current_revision"
        )
    )
    lifecycle_projection: Mapped[str] = mapped_column(String(20), default="DRAFT")


class Quote(Snapshot, TradeBase):
    __tablename__ = "freight_quote_revisions"
    __table_args__ = (UniqueConstraint("quote_head_id", "revision_number"),)
    quote_head_id: Mapped[str] = mapped_column(ForeignKey(QuoteHead.id))
    revision_number: Mapped[int] = mapped_column(Integer)
    prior_revision_id: Mapped[str | None] = mapped_column(ForeignKey("freight_quote_revisions.id"))
    route_template_revision_id: Mapped[str] = mapped_column(ForeignKey(Template.id))
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("op_vehicles.id"))
    driver_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    profile_revision_id: Mapped[str] = mapped_column(ForeignKey(Profile.id))
    source_context_hash: Mapped[str] = mapped_column(String(64))
    valid_from: Mapped[datetime] = mapped_column(TS)
    accept_by: Mapped[datetime] = mapped_column(TS)
    carrier_net_minor: Mapped[int] = mapped_column(BigInteger)
    carrier_charged_tax_minor: Mapped[int | None] = mapped_column(BigInteger)
    carrier_payable_total_minor: Mapped[int | None] = mapped_column(BigInteger)
    quote_json: Mapped[dict] = mapped_column(JSON_TYPE)


class QuoteEvent(Record, TradeBase):
    __tablename__ = "freight_quote_events"
    quote_revision_id: Mapped[str] = mapped_column(ForeignKey(Quote.id), index=True)
    event_type: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class Assumptions(Snapshot, TradeBase):
    __tablename__ = "tradetwin_cost_assumption_revisions"
    __table_args__ = (
        UniqueConstraint("consignment_id", "owner_organisation_id", "revision_number"),
    )
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"))
    owner_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    revision_number: Mapped[int] = mapped_column(Integer)
    assumptions_json: Mapped[dict] = mapped_column(JSON_TYPE)


class AssumptionReview(Record, TradeBase):
    __tablename__ = "tradetwin_cost_assumption_reviews"
    assumption_revision_id: Mapped[str] = mapped_column(ForeignKey(Assumptions.id))
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class Run(Snapshot, TradeBase):
    __tablename__ = "tradetwin_runs"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    owner_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("tradetwin_runs.id"))
    execution_mode: Mapped[str] = mapped_column(String(20))
    input_json: Mapped[dict] = mapped_column(JSON_TYPE)
    job_state: Mapped[str] = mapped_column(String(20), default="QUEUED")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    engine_version: Mapped[str] = mapped_column(String(50))
    evaluated_as_of: Mapped[datetime] = mapped_column(TS)
    completed_at: Mapped[datetime | None] = mapped_column(TS)
    result_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    result_hash: Mapped[str | None] = mapped_column(String(64))


class Generation(Snapshot, TradeBase):
    __tablename__ = "routing_generation_jobs"
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"))
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"))
    input_json: Mapped[dict] = mapped_column(JSON_TYPE)
    job_state: Mapped[str] = mapped_column(String(20), default="QUEUED")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("doc_processing_jobs.id"))
    result_json: Mapped[dict | None] = mapped_column(JSON_TYPE)


class Candidate(Snapshot, TradeBase):
    __tablename__ = "tradetwin_candidates"
    __table_args__ = (UniqueConstraint("run_id", "quote_revision_id"),)
    run_id: Mapped[str] = mapped_column(ForeignKey(Run.id), index=True)
    quote_revision_id: Mapped[str] = mapped_column(ForeignKey(Quote.id))
    route_template_revision_id: Mapped[str] = mapped_column(ForeignKey(Template.id))
    candidate_json: Mapped[dict] = mapped_column(JSON_TYPE)
    planning_outcome: Mapped[str] = mapped_column(String(30), index=True)
    cost_completeness: Mapped[str] = mapped_column(String(30))
    ranking_eligibility: Mapped[str] = mapped_column(String(20))


class SelectionHead(Mutable, TradeBase):
    __tablename__ = "tradetwin_selection_heads"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), unique=True)
    current_proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "tradetwin_selection_proposals.id",
            use_alter=True,
            name="fk_freight_selection_current_proposal",
        )
    )
    lifecycle_projection: Mapped[str] = mapped_column(String(30), default="CANCELLED")
    proposed_assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("op_transport_assignments.id")
    )
    current_commitment_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "freight_commitments.id", use_alter=True, name="fk_freight_selection_current_commitment"
        )
    )


class Selection(Snapshot, TradeBase):
    __tablename__ = "tradetwin_selection_proposals"
    selection_head_id: Mapped[str] = mapped_column(ForeignKey(SelectionHead.id))
    run_id: Mapped[str] = mapped_column(ForeignKey(Run.id))
    candidate_id: Mapped[str] = mapped_column(ForeignKey(Candidate.id))
    quote_revision_id: Mapped[str] = mapped_column(ForeignKey(Quote.id))
    proposal_json: Mapped[dict] = mapped_column(JSON_TYPE)
    approval_deadline: Mapped[datetime] = mapped_column(TS)


class Decision(Record, TradeBase):
    __tablename__ = "tradetwin_selection_decisions"
    __table_args__ = (UniqueConstraint("proposal_id", "decision_role"),)
    proposal_id: Mapped[str] = mapped_column(ForeignKey(Selection.id))
    decision_role: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(20))
    proposal_hash: Mapped[str] = mapped_column(String(64))
    quote_hash: Mapped[str] = mapped_column(String(64))
    acknowledged_limitations_json: Mapped[list] = mapped_column(JSON_TYPE)
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class Commitment(Snapshot, TradeBase):
    __tablename__ = "freight_commitments"
    selection_proposal_id: Mapped[str] = mapped_column(ForeignKey(Selection.id), unique=True)
    trade_id: Mapped[str] = mapped_column(ForeignKey("trades.id"), index=True)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    accepted_assignment_id: Mapped[str] = mapped_column(
        ForeignKey("op_transport_assignments.id"), unique=True
    )
    quote_revision_id: Mapped[str] = mapped_column(ForeignKey(Quote.id))
    commitment_json: Mapped[dict] = mapped_column(JSON_TYPE)
    execution_mode: Mapped[str] = mapped_column(String(20))


class CommitmentEvent(Record, TradeBase):
    __tablename__ = "freight_commitment_events"
    commitment_id: Mapped[str] = mapped_column(ForeignKey(Commitment.id), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    event_json: Mapped[dict] = mapped_column(JSON_TYPE)
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


class RoutePlan(Snapshot, TradeBase):
    __tablename__ = "consignment_route_plan_revisions"
    __table_args__ = (UniqueConstraint("consignment_id", "revision_number"),)
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    freight_commitment_id: Mapped[str] = mapped_column(ForeignKey(Commitment.id))
    accepted_assignment_id: Mapped[str] = mapped_column(ForeignKey("op_transport_assignments.id"))
    route_plan_json: Mapped[dict] = mapped_column(JSON_TYPE)


class PlanHead(Mutable, TradeBase):
    __tablename__ = "consignment_route_plan_heads"
    consignment_id: Mapped[str] = mapped_column(ForeignKey("op_consignments.id"), unique=True)
    current_revision_id: Mapped[str | None] = mapped_column(ForeignKey(RoutePlan.id))


class Cancellation(Mutable, TradeBase):
    __tablename__ = "freight_cancellation_proposals"
    commitment_id: Mapped[str] = mapped_column(ForeignKey(Commitment.id))
    commitment_hash: Mapped[str] = mapped_column(String(64))
    cancellation_json: Mapped[dict] = mapped_column(JSON_TYPE)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")


class CancellationDecision(Record, TradeBase):
    __tablename__ = "freight_cancellation_decisions"
    __table_args__ = (UniqueConstraint("cancellation_proposal_id", "decision_role"),)
    cancellation_proposal_id: Mapped[str] = mapped_column(ForeignKey(Cancellation.id))
    decision_role: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(20))
    proposal_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(2000))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))
    actor_organisation_id: Mapped[str] = mapped_column(ForeignKey("trade_organizations.id"))


class ResourceVersion(TradeBase):
    __tablename__ = "transport_resource_versions"
    execution_mode: Mapped[str] = mapped_column(String(20), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, default=1)


class Provider(Mutable, TradeBase):
    __tablename__ = "routing_provider_connections"
    organisation_id: Mapped[str | None] = mapped_column(ForeignKey("trade_organizations.id"))
    provider_code: Mapped[str] = mapped_column(String(50))
    environment: Mapped[str] = mapped_column(String(20))
    vault_secret_reference: Mapped[str] = mapped_column(String(200))
    capabilities_json: Mapped[dict] = mapped_column(JSON_TYPE)
    licensing_json: Mapped[dict] = mapped_column(JSON_TYPE)
    approved_hosts_json: Mapped[list] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")


class GraphNode(TradeBase):
    __tablename__ = "route_graph_nodes"
    dataset_revision_id: Mapped[str] = mapped_column(ForeignKey(Dataset.id), primary_key=True)
    node_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    state_code: Mapped[str] = mapped_column(String(2))
    node_kind: Mapped[str] = mapped_column(String(30))


class GraphEdge(TradeBase):
    __tablename__ = "route_graph_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_revision_id", "from_node_key"],
            ["route_graph_nodes.dataset_revision_id", "route_graph_nodes.node_key"],
        ),
        ForeignKeyConstraint(
            ["dataset_revision_id", "to_node_key"],
            ["route_graph_nodes.dataset_revision_id", "route_graph_nodes.node_key"],
        ),
    )
    dataset_revision_id: Mapped[str] = mapped_column(ForeignKey(Dataset.id), primary_key=True)
    edge_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    from_node_key: Mapped[str] = mapped_column(String(100))
    to_node_key: Mapped[str] = mapped_column(String(100))
    distance_meters: Mapped[int] = mapped_column(BigInteger)
    estimated_driving_seconds: Mapped[int] = mapped_column(Integer)
    edge_json: Mapped[dict] = mapped_column(JSON_TYPE)


class RunDependency(Record, TradeBase):
    __tablename__ = "tradetwin_run_dependencies"
    run_id: Mapped[str] = mapped_column(ForeignKey(Run.id), index=True)
    dependency_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    dependency_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ConstraintResult(Record, TradeBase):
    __tablename__ = "tradetwin_candidate_constraint_results"
    candidate_id: Mapped[str] = mapped_column(ForeignKey(Candidate.id), index=True)
    category: Mapped[str] = mapped_column(String(50))
    requirement_code: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(20))
    result_json: Mapped[dict] = mapped_column(JSON_TYPE)


class CostItem(Record, TradeBase):
    __tablename__ = "tradetwin_candidate_cost_items"
    candidate_id: Mapped[str] = mapped_column(ForeignKey(Candidate.id), index=True)
    scenario_code: Mapped[str] = mapped_column(String(30))
    component_code: Mapped[str] = mapped_column(String(50))
    origin: Mapped[str] = mapped_column(String(40))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    calculation_json: Mapped[dict] = mapped_column(JSON_TYPE)


class ScenarioResult(Record, TradeBase):
    __tablename__ = "tradetwin_scenario_results"
    __table_args__ = (UniqueConstraint("candidate_id", "scenario_code"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey(Candidate.id))
    scenario_code: Mapped[str] = mapped_column(String(30))
    estimated_departure_at: Mapped[datetime] = mapped_column(TS)
    estimated_arrival_at: Mapped[datetime] = mapped_column(TS)
    comparison_total_minor: Mapped[int | None] = mapped_column(BigInteger)
    result_json: Mapped[dict] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))


class Ranking(Record, TradeBase):
    __tablename__ = "tradetwin_ranking_results"
    __table_args__ = (UniqueConstraint("run_id", "scenario_code", "objective", "candidate_id"),)
    run_id: Mapped[str] = mapped_column(ForeignKey(Run.id))
    candidate_id: Mapped[str] = mapped_column(ForeignKey(Candidate.id))
    scenario_code: Mapped[str] = mapped_column(String(30))
    objective: Mapped[str] = mapped_column(String(40))
    rank: Mapped[int] = mapped_column(Integer)
    pareto_member: Mapped[bool] = mapped_column(Boolean)
    score_numerator: Mapped[str] = mapped_column(String(100))
    score_denominator: Mapped[str] = mapped_column(String(100))
    ranking_json: Mapped[dict] = mapped_column(JSON_TYPE)


class SelectionEvent(Record, TradeBase):
    __tablename__ = "tradetwin_selection_events"
    proposal_id: Mapped[str] = mapped_column(ForeignKey(Selection.id), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    event_json: Mapped[dict] = mapped_column(JSON_TYPE)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("trade_users.id"))


TABLES = [
    Location,
    LocationHead,
    Profile,
    Dataset,
    DatasetEvent,
    Template,
    RFQ,
    Invitation,
    QuoteHead,
    Quote,
    QuoteEvent,
    Assumptions,
    AssumptionReview,
    Run,
    Generation,
    Candidate,
    SelectionHead,
    Selection,
    Decision,
    Commitment,
    CommitmentEvent,
    RoutePlan,
    PlanHead,
    Cancellation,
    CancellationDecision,
    ResourceVersion,
    Provider,
    GraphNode,
    GraphEdge,
    RunDependency,
    ConstraintResult,
    CostItem,
    ScenarioResult,
    Ranking,
    SelectionEvent,
]
IMMUTABLE_TABLES = [
    m.__tablename__ for m in TABLES if issubclass(m, Snapshot) and m not in {Run, Generation}
]
IMMUTABLE_TABLES += [
    DatasetEvent.__tablename__,
    QuoteEvent.__tablename__,
    Decision.__tablename__,
    CommitmentEvent.__tablename__,
    AssumptionReview.__tablename__,
    CancellationDecision.__tablename__,
    GraphNode.__tablename__,
    GraphEdge.__tablename__,
    RunDependency.__tablename__,
    ConstraintResult.__tablename__,
    CostItem.__tablename__,
    ScenarioResult.__tablename__,
    Ranking.__tablename__,
    SelectionEvent.__tablename__,
]
