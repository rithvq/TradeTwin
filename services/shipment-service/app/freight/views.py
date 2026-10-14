"""One permission-filtered projection for UI, graph, risk and evidence replay."""

from copy import deepcopy

from sqlalchemy import select

from app.compliance.clock import aware, instant
from app.operations.access import exists, fail, has
from app.operations.ledger import view
from app.trades.access import grants, membership, require
from app.trades.models import Trade
from app.trades.terms import digest

from .access import base_context, planning, price_access, rfq_access
from .models import (
    RFQ,
    Commitment,
    CommitmentEvent,
    Dataset,
    Location,
    PlanHead,
    Quote,
    QuoteHead,
    RoutePlan,
    Run,
    Selection,
    SelectionHead,
)
from .offers import quote_status
from .runs import fresh


def context_view(db, ctx, ident):
    trade, cn = planning(db, ctx, ident)
    base = base_context(db, trade, cn)
    base.update(
        reference=cn.reference,
        consignment_etag=f'"{cn.row_version}"',
        context_etag=f'"{base["compliance_context_version"]}"',
        pickup_address_hash=digest(cn.pickup_address_snapshot),
        drop_address_hash=digest(cn.delivery_address_snapshot),
        capabilities=sorted(
            {g.permission_code for g in grants(db, membership(db, ctx.user, ctx.org_id), trade.id)}
        ),
        price_visible=price_access(db, ctx, trade),
        locations=[
            view(location)
            for location in db.scalars(
                select(Location)
                .where(Location.consignment_id == cn.id)
                .order_by(Location.revision_number.desc())
            )
        ],
        rfqs=[
            rfq_view(db, ctx, r.id)
            for r in db.scalars(
                select(RFQ).where(RFQ.consignment_id == cn.id).order_by(RFQ.created_at.desc())
            )
        ],
        runs=[
            {
                "id": r.id,
                "job_state": r.job_state,
                "freshness": fresh(db, r, trade, cn),
                "evaluated_as_of": aware(r.evaluated_as_of).isoformat(),
            }
            for r in db.scalars(
                select(Run)
                .where(Run.consignment_id == cn.id)
                .order_by(Run.created_at.desc())
                .limit(20)
            )
        ],
    )
    head = db.scalar(select(SelectionHead).where(SelectionHead.consignment_id == cn.id))
    base["selection"] = (
        selection_view(db, ctx, head.current_proposal_id)
        if head and head.current_proposal_id
        else None
    )
    base["route_plan"] = route_plan(db, ctx, cn.id)
    base["datasets"] = [
        {
            "id": d.id,
            "dataset_code": d.dataset_code,
            "version": d.version,
            "source_kind": d.dataset_json["source_kind"],
            "limitations": d.dataset_json["limitations"],
        }
        for d in db.scalars(select(Dataset).where(Dataset.execution_mode == trade.execution_mode))
    ]
    return base


def quote_view(db, ctx, ident):
    quote = exists(db, Quote, ident)
    head = exists(db, QuoteHead, quote.quote_head_id)
    rfq, trade, _, carrier = rfq_access(db, ctx, head.rfq_id)
    if carrier and head.carrier_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Offer not found.", status=404)
    lifecycle, effective = quote_status(db, quote, instant(db))
    if carrier or price_access(db, ctx, trade, rfq.freight_payer_organisation_id):
        return {
            **view(quote),
            "lifecycle": lifecycle,
            "effective_expiration": effective,
            "head_etag": f'"{head.row_version}"',
        }
    # Even rankings/savings labels can disclose private prices. Do not return them masked.
    data = quote.quote_json
    return {
        "id": quote.id,
        "route_template_revision_id": quote.route_template_revision_id,
        "vehicle_id": quote.vehicle_id,
        "profile_revision_id": quote.profile_revision_id,
        "quote_hash": quote.content_hash,
        "lifecycle": lifecycle,
        "effective_expiration": effective,
        "carrier_organisation_id": head.carrier_organisation_id,
        "quote_json": {
            k: data[k]
            for k in [
                "offered_pickup_window_start",
                "offered_pickup_window_end",
                "offered_delivery_window_start",
                "offered_delivery_window_end",
                "valid_from",
                "accept_by",
            ]
        },
        "price_visible": False,
    }


def rfq_view(db, ctx, ident):
    row, trade, cn, carrier = rfq_access(db, ctx, ident)
    quotes = list(
        db.scalars(
            select(Quote)
            .join(QuoteHead, Quote.quote_head_id == QuoteHead.id)
            .where(QuoteHead.rfq_id == row.id, QuoteHead.current_revision_id == Quote.id)
        )
    )
    if carrier:
        quotes = [
            q
            for q in quotes
            if db.get(QuoteHead, q.quote_head_id).carrier_organisation_id == ctx.org_id
        ]
    data = {
        "id": row.id,
        "request_hash": row.content_hash,
        "execution_mode": row.execution_mode,
        "lifecycle": row.lifecycle_projection,
        "etag": f'"{row.row_version}"',
        "response_deadline": aware(row.response_deadline).isoformat(),
        "request": deepcopy(row.request_json),
        "quotes": [quote_view(db, ctx, q.id) for q in quotes],
    }
    if carrier:
        data["request"].pop("invited_carrier_organisation_ids", None)
        data["selection_requests"] = [
            {"id": s.id, "lifecycle": h.lifecycle_projection}
            for h, s in db.execute(
                select(SelectionHead, Selection)
                .join(Selection, Selection.id == SelectionHead.current_proposal_id)
                .where(SelectionHead.consignment_id == cn.id)
            )
            if s.proposal_json["carrier_organisation_id"] == ctx.org_id
            and db.get(QuoteHead, db.get(Quote, s.quote_revision_id).quote_head_id).rfq_id == row.id
        ]
    else:
        data["freshness"] = (
            "CURRENT"
            if base_context(db, trade, cn)["planning_context_hash"] == row.context_hash
            else "STALE"
        )
    return data


def run_view(db, ctx, ident):
    row = exists(db, Run, ident)
    trade, cn = planning(db, ctx, row.consignment_id)
    data = deepcopy(row.result_json or {"candidates": [], "rankings": {}})
    visible = price_access(
        db, ctx, trade, row.input_json["context"]["freight_payer_organisation_id"]
    )
    from app.corridor.service import event_visible

    for candidate in data["candidates"]:
        for scenario in candidate["scenarios"].values():
            impact = scenario.get("corridor_impact")
            if impact:
                impact["items"] = [
                    item
                    if event_visible(db, ctx, item)
                    else {
                        "outcome": item["outcome"],
                        "edge_key": item["edge_key"],
                        "limitations": ["Restricted source evidence."],
                    }
                    for item in impact["items"]
                ]
    if not visible:
        data.pop("rankings", None)
        data.pop("pareto_frontier", None)
        data.pop("eligible_baseline_comparison", None)
        data.pop("rankable_candidate_count", None)
        for candidate in data["candidates"]:
            for scenario in candidate["scenarios"].values():
                scenario.pop("cost", None)
                scenario.pop("ranking_eligibility", None)
                scenario["why_excluded"] = [
                    c for c in scenario["why_excluded"] if not c.startswith("COST")
                ]
    # IDs are operational stable order, never private cost order.
    data["candidates"] = sorted(data["candidates"], key=lambda c: c["candidate_id"])
    return {
        **data,
        "id": row.id,
        "input_hash": row.content_hash,
        "result_hash": row.result_hash,
        "job_state": row.job_state,
        "execution_mode": row.execution_mode,
        "freshness": fresh(db, row, trade, cn),
        "evaluated_as_of": aware(row.evaluated_as_of).isoformat(),
        "price_visible": visible,
        "permitted_next_actions": ["PREPARE_BASE_SELECTION", "FRESH_PHASE4_REQUIRED"]
        if row.job_state == "COMPLETED"
        else ["WAIT_FOR_WORKER"],
    }


def selection_view(db, ctx, ident):
    row = exists(db, Selection, ident)
    head = exists(db, SelectionHead, row.selection_head_id)
    trade = exists(db, Trade, row.proposal_json["trade_id"])
    carrier = ctx.org_id == row.proposal_json["carrier_organisation_id"]
    if carrier:
        require(db, ctx.user, ctx.org_id, "freight.offer.accept", trade.id)
    else:
        planning(db, ctx, head.consignment_id)
    value = deepcopy(row.proposal_json)
    if not price_access(db, ctx, trade, row.proposal_json["freight_payer_organisation_id"]):
        value.pop("comparison_cost_snapshot", None)
    if carrier:
        # Own fixed offered price only; never private external payer estimates.
        value["own_offer"] = quote_view(db, ctx, row.quote_revision_id)
    status = head.lifecycle_projection
    if status in {"PENDING_APPROVALS", "PENDING_CARRIER_ACCEPTANCE"}:
        from app.operations.models import Consignment

        if instant(db) >= row.approval_deadline.replace(tzinfo=instant(db).tzinfo):
            status = "EXPIRED"
        elif (
            fresh(
                db, exists(db, Run, row.run_id), trade, exists(db, Consignment, head.consignment_id)
            )
            != "CURRENT"
        ):
            status = "STALE"
    from .models import Decision

    decisions = [
        {"role": d.decision_role, "decision": d.decision, "proposal_hash": d.proposal_hash}
        for d in db.scalars(select(Decision).where(Decision.proposal_id == row.id))
    ]
    return {
        "id": row.id,
        "proposal": value,
        "proposal_hash": row.content_hash,
        "quote_hash": value["quote_hash"],
        "lifecycle": status,
        "etag": f'"{head.row_version}"',
        "proposed_assignment_id": head.proposed_assignment_id,
        "commitment_id": head.current_commitment_id,
        "decisions": decisions,
    }


def commitment_view(db, ctx, ident):
    row = exists(db, Commitment, ident)
    from app.operations.access import consignment

    own_carrier = ctx.org_id == row.commitment_json["carrier_organisation_id"] and has(
        db, ctx, "freight.rfq.invited.read", row.trade_id
    )
    if own_carrier:
        trade = exists(db, Trade, row.trade_id)
    else:
        trade, _, _ = consignment(db, ctx, row.consignment_id)
    value = deepcopy(row.commitment_json)
    if not price_access(db, ctx, trade, row.commitment_json["freight_payer_organisation_id"]):
        for key in ["comparison_cost_snapshot"] + (
            []
            if own_carrier
            else ["price_snapshot", "service_snapshot", "cancellation_terms_snapshot"]
        ):
            value.pop(key, None)
    events = [
        {"event_type": e.event_type, "occurred_at": aware(e.created_at).isoformat()}
        for e in db.scalars(
            select(CommitmentEvent)
            .where(CommitmentEvent.commitment_id == row.id)
            .order_by(CommitmentEvent.created_at)
        )
    ]
    return {
        "id": row.id,
        "content_hash": row.content_hash,
        "commitment": value,
        "events": events,
        "execution_mode": row.execution_mode,
    }


def route_plan(db, ctx, ident):
    from app.operations.access import consignment

    _, _, _ = consignment(db, ctx, ident)
    head = db.scalar(select(PlanHead).where(PlanHead.consignment_id == str(ident)))
    return (
        view(exists(db, RoutePlan, head.current_revision_id))
        if head and head.current_revision_id
        else None
    )


def evidence(db, ctx, ident, kind="run"):
    data = run_view(db, ctx, ident) if kind == "run" else commitment_view(db, ctx, ident)
    from .models import Dataset, Template

    if kind == "run":
        row = exists(db, Run, ident)
        for source in row.input_json["sources"]:
            if not source["dataset"]["export_allowed"]:
                fail(
                    "SOURCE_EXPORT_NOT_PERMITTED",
                    "A source licence prohibits export; inspect the permitted on-screen decision.",
                    status=403,
                )
    else:
        quote = exists(db, Quote, exists(db, Commitment, ident).quote_revision_id)
        ds = exists(
            db, Dataset, exists(db, Template, quote.route_template_revision_id).dataset_revision_id
        )
        if not ds.dataset_json["export_allowed"]:
            fail(
                "SOURCE_EXPORT_NOT_PERMITTED",
                "The retained route source is not licensed for export.",
                status=403,
            )
    return {
        "schema_version": "TRADETWIN_EVIDENCE_V1",
        "record": data,
        "input_manifest": {
            "context": {k: v for k, v in row.input_json["context"].items() if k != "inherited"},
            "planning_intent": row.input_json["planning_intent"],
            "deadline": row.input_json["deadline"],
            "objective": row.input_json["objective"],
            "weights": row.input_json["balanced_weights"],
            "comparison_policy": row.input_json["comparison_policy"],
            "scenarios": row.input_json["scenarios"],
            "registry_manifest": row.input_json["registry_manifest"],
            "cost_assumptions": row.input_json["cost_assumptions"]
            if data.get("price_visible")
            else None,
        }
        if kind == "run"
        else None,
        "integrity_notice": "Hashes prove content integrity, not source truth or legal clearance.",
    }


def graph(db, ctx, ident):
    data = run_view(db, ctx, ident)
    row = exists(db, Run, ident)
    nodes, edges = [], []

    def node(key, kind, label, details=None):
        nodes.append({"id": str(key), "type": kind, "label": label, "details": details})

    def edge(source, target, kind):
        edges.append({"source": str(source), "target": str(target), "type": kind})

    node(ident, "TradeTwinRun", "Comparison as of " + data["evaluated_as_of"])
    base = row.input_json["context"]
    node(base["consignment_id"], "Consignment", "Pre-pickup transport plan")
    edge(base["consignment_id"], ident, "COMPARED_BY")
    assumption_id = row.input_json["cost_assumption_revision_id"]
    if data["price_visible"] and assumption_id:
        node(assumption_id, "CostAssumptions", "Private reviewed payer declaration")
        edge(assumption_id, ident, "DECLARES_ESTIMATES")
    sources = {s["quote_revision_id"]: s for s in row.input_json["sources"]}
    for c in data["candidates"]:
        node(
            c["candidate_id"],
            "Candidate",
            "Offer "
            + c.get("offer_label", c["quote_revision_id"][:8])
            + " / "
            + c["scenarios"]["BASE"]["planning_outcome"],
            c["scenarios"]["BASE"],
        )
        edge(ident, c["candidate_id"], "EVALUATED")
        for key, kind in [("quote_revision_id", "Quote"), ("route_template_revision_id", "Route")]:
            node(c[key], kind, kind + " " + c[key][:8])
            edge(c["candidate_id"], c[key], "USES_" + kind.upper())
        quote = exists(db, Quote, c["quote_revision_id"])
        head = exists(db, QuoteHead, quote.quote_head_id)
        node(head.rfq_id, "RFQ", "Published route-specific request")
        edge(head.rfq_id, quote.id, "RECEIVED_OFFER")
        edge(head.rfq_id, row.id, "OFFERS_COMPARED_BY")
        source = sources[quote.id]
        node(quote.profile_revision_id, "VehicleProfile", "Immutable nominated vehicle profile")
        edge(quote.id, quote.profile_revision_id, "NOMINATES_PROFILE")
        dataset_id = source["template"]["dataset_revision_id"]
        node(dataset_id, "RouteDataset", "Retained dataset / " + source["dataset"]["version"])
        edge(c["route_template_revision_id"], dataset_id, "RETAINS_SOURCE")
        constraints = c["scenarios"]["BASE"]["planning_constraint_results"]
        passed = [r for r in constraints if r["outcome"] == "PASS"]
        if passed:
            key = f"{c['candidate_id']}:confirmed-checks"
            node(
                key,
                "PlanningConstraint",
                f"{len(passed)} confirmed planning checks",
                {"results": passed},
            )
            edge(c["candidate_id"], key, "CONFIRMED_CHECKS")
        for index, constraint in enumerate(constraints):
            if constraint["outcome"] == "PASS":
                continue
            key = f"{c['candidate_id']}:constraint:{index}"
            node(
                key,
                "PlanningConstraint",
                constraint["requirement_code"] + " / " + constraint["outcome"],
                constraint,
            )
            edge(c["candidate_id"], key, "ASSESSED_AGAINST")
    for selection in db.scalars(select(Selection).where(Selection.run_id == row.id)):
        node(selection.id, "SelectionProposal", "Exact-hash selection")
        edge(selection.candidate_id, selection.id, "PROPOSED_FROM")
        committed = db.scalar(
            select(Commitment).where(Commitment.selection_proposal_id == selection.id)
        )
        if committed:
            node(committed.id, "FreightCommitment", "Bilateral fixed freight commitment")
            edge(selection.id, committed.id, "COMMITTED_AS")
            node(
                committed.accepted_assignment_id,
                "CommittedAssignment",
                "Accepted Phase 2 resource bookings",
            )
            edge(committed.id, committed.accepted_assignment_id, "ACCEPTED_ASSIGNMENT")
            for plan in db.scalars(
                select(RoutePlan).where(RoutePlan.freight_commitment_id == committed.id)
            ):
                node(plan.id, "OperationalRoutePlan", "Immutable operational corridor")
                edge(committed.id, plan.id, "APPLIED_ROUTE_PLAN")
            from app.compliance.models import Heads

            compliance = db.get(Heads, committed.consignment_id)
            if compliance:
                for evaluation_id in [
                    compliance.current_pickup_evaluation_id,
                    compliance.current_departure_evaluation_id,
                ]:
                    if evaluation_id:
                        node(
                            evaluation_id,
                            "ActualDispatchEvaluation",
                            "Actual Phase 4 reevaluation / not a candidate release",
                        )
                        edge(
                            committed.accepted_assignment_id,
                            evaluation_id,
                            "REEVALUATED_FOR_RELEASE",
                        )
    unique_edges = {(e["source"], e["target"], e["type"]): e for e in edges}
    return {
        "nodes": list({n["id"]: n for n in nodes}.values()),
        "edges": list(unique_edges.values()),
    }


def quote_history(db, ctx, ident):
    head = db.get(QuoteHead, ident)
    if head is None:
        return quote_view(db, ctx, ident)
    _, _, _, carrier = rfq_access(db, ctx, head.rfq_id)
    if carrier and head.carrier_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Offer not found.", status=404)
    return {
        "id": head.id,
        "etag": f'"{head.row_version}"',
        "current_revision_id": head.current_revision_id,
        "lifecycle": head.lifecycle_projection,
        "revisions": [
            quote_view(db, ctx, q.id)
            for q in db.scalars(
                select(Quote).where(Quote.quote_head_id == head.id).order_by(Quote.revision_number)
            )
        ],
    }
