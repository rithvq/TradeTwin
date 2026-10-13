"""Exact-hash approvals and atomic acceptance through existing Phase 2 bookings."""

from copy import deepcopy
from datetime import timedelta

from sqlalchemy import select

from app.compliance import context
from app.compliance.clock import aware, instant
from app.operations import transport
from app.operations.access import aligned, before_pickup, exists, fail, lock_trade
from app.operations.ledger import record, touch, view
from app.operations.models import Assignment, Booking, Consignment
from app.operations.schemas import AssignmentDecision
from app.trades.access import require
from app.trades.context_locks import bump_context
from app.trades.models import Trade, uid
from app.trades.terms import digest

from .access import base_context, planning
from .assessment import POST_SELECTION
from .models import (
    AssumptionReview,
    Assumptions,
    Cancellation,
    CancellationDecision,
    Candidate,
    Commitment,
    CommitmentEvent,
    Decision,
    PlanHead,
    Quote,
    QuoteEvent,
    QuoteHead,
    RoutePlan,
    Run,
    Selection,
    SelectionHead,
)
from .offers import quote_status
from .routing import aware_from, latest_number
from .runs import fresh


def exact(db, ctx, ident, role=None, lock=True):
    row = exists(db, Selection, ident)
    head = exists(db, SelectionHead, row.selection_head_id)
    cn = exists(db, Consignment, head.consignment_id)
    trade = lock_trade(db, cn.trade_id) if lock else exists(db, Trade, cn.trade_id)
    if lock:
        db.refresh(head)
        db.refresh(cn)
    proposal = row.proposal_json
    if role == "CARRIER":
        if ctx.org_id != proposal["carrier_organisation_id"]:
            fail("NOT_FOUND", "Selection request not found.", status=404)
        require(db, ctx.user, ctx.org_id, "freight.offer.accept", trade.id)
        require(db, ctx.user, ctx.org_id, "assignment.respond", trade.id)
    elif role:
        expected = (
            proposal["freight_payer_organisation_id"]
            if role == "PAYER"
            else proposal["coordinating_organisation_id"]
        )
        if ctx.org_id != expected:
            fail(
                "FORBIDDEN",
                "Only the responsible organisation can record this decision.",
                status=403,
            )
        require(
            db,
            ctx.user,
            ctx.org_id,
            "freight.commit.approve" if role == "PAYER" else "tradetwin.plan.apply",
            trade.id,
        )
    else:
        planning(db, ctx, cn.id, "tradetwin.selection.prepare", lock)
    return row, head, trade, cn


def current(db, row, head, trade, cn):
    if head.current_proposal_id != row.id or head.lifecycle_projection not in {
        "PENDING_APPROVALS",
        "PENDING_CARRIER_ACCEPTANCE",
    }:
        fail("RUN_STALE", "Selection is no longer current.")
    if instant(db) >= aware(row.approval_deadline):
        fail("QUOTE_EXPIRED", "Acceptance deadline has passed.")
    if fresh(db, exists(db, Run, row.run_id), trade, cn) != "CURRENT":
        fail("RUN_STALE", "A relevant input changed; create a fresh comparison and approvals.")
    before_pickup(cn)
    aligned(cn)
    if cn.active_assignment_id != row.proposal_json["expected_existing_assignment_id"]:
        fail("RUN_STALE", "Current assignment changed.")


def propose(db, ctx, ident, payload):
    if payload.scenario_code != "BASE":
        fail(
            "SCENARIO_NOT_COMMITTABLE",
            "Stress scenarios cannot become commitments; create a new BASE intent.",
        )
    trade, cn = planning(db, ctx, ident, "tradetwin.selection.prepare", True)
    if ctx.org_id != cn.coordinating_organization_id:
        fail("FORBIDDEN", "Only the coordinator can propose the operational plan.", status=403)
    before_pickup(cn)
    aligned(cn)
    base = base_context(db, trade, cn)
    if (
        payload.expected_consignment_row_version != cn.row_version
        or payload.expected_context_version != base["compliance_context_version"]
        or ctx.if_match != f'"{cn.row_version}"'
        or (
            str(payload.expected_existing_assignment_id)
            if payload.expected_existing_assignment_id
            else None
        )
        != cn.active_assignment_id
    ):
        fail("RUN_STALE", "Reload current consignment and compliance versions.", status=412)
    run = exists(db, Run, payload.run_id)
    candidate = exists(db, Candidate, payload.candidate_id)
    quote = exists(db, Quote, payload.quote_revision_id)
    if (
        run.consignment_id != cn.id
        or candidate.run_id != run.id
        or candidate.quote_revision_id != quote.id
    ):
        fail("NOT_FOUND", "Candidate not found.", status=404)
    if candidate.content_hash != payload.candidate_hash or quote.content_hash != payload.quote_hash:
        fail("APPROVAL_HASH_MISMATCH", "Selection hashes do not match immutable candidate/offer.")
    if run.job_state != "COMPLETED" or fresh(db, run, trade, cn) != "CURRENT":
        fail("RUN_STALE", "Only current completed runs can be selected.")
    if candidate.ranking_eligibility != "RANKABLE":
        fail(
            "CANDIDATE_NOT_RANKABLE",
            "Hard planning requirements and complete comparable costs are required.",
            details={
                "blocking_constraint_ids": candidate.candidate_json["scenarios"]["BASE"][
                    "why_excluded"
                ]
            },
        )
    if run.input_json["cost_assumption_revision_id"]:
        assumed = exists(db, Assumptions, run.input_json["cost_assumption_revision_id"])
        review = db.scalar(
            select(AssumptionReview)
            .where(AssumptionReview.assumption_revision_id == assumed.id)
            .order_by(AssumptionReview.created_at.desc(), AssumptionReview.id.desc())
        )
        if not review or review.decision != "APPROVE_DECLARATION":
            fail(
                "COST_ASSUMPTION_REVIEW_REQUIRED",
                "Private cost declaration requires independent payer review.",
            )
    head = db.scalar(select(SelectionHead).where(SelectionHead.consignment_id == cn.id))
    if head and head.current_commitment_id:
        fail(
            "COMMITMENT_CANCELLATION_REQUIRED",
            "Cancel the active priced commitment bilaterally before replacement.",
        )
    if head and head.lifecycle_projection in {"PENDING_APPROVALS", "PENDING_CARRIER_ACCEPTANCE"}:
        fail("SELECTION_ALREADY_PENDING", "Cancel the existing proposal before selecting another.")
    if not head:
        head = SelectionHead(consignment_id=cn.id, created_by=ctx.user.id)
        db.add(head)
        db.flush()
    scenario = candidate.candidate_json["scenarios"]["BASE"]
    value = {
        **payload.model_dump(mode="json"),
        "schema_version": 1,
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "accepted_trade_revision_id": trade.accepted_revision_id,
        "freight_payer_organisation_id": base["freight_payer_organisation_id"],
        "coordinating_organisation_id": cn.coordinating_organization_id,
        "carrier_organisation_id": quote.quote_json["carrier_organisation_id"],
        "input_hash": run.content_hash,
        "source_context_hash": base["planning_context_hash"],
        "selected_route_snapshot": scenario["route"],
        "selected_timing_snapshot": {
            k: scenario[k]
            for k in ["estimated_departure_at", "estimated_arrival_at", "estimated_completion_at"]
        },
        "selected_resource_snapshot": {
            "vehicle_id": quote.vehicle_id,
            "driver_user_id": quote.driver_user_id,
            "profile_revision_id": quote.profile_revision_id,
        },
        "comparison_cost_snapshot": scenario["cost"],
        "acknowledged_limitations_required": [
            "ESTIMATE_NOT_GUARANTEE",
            "AVAILABILITY_NOT_RESERVATION",
            "FRESH_PHASE4_RELEASE_REQUIRED",
        ],
        "execution_mode": trade.execution_mode,
    }
    row = Selection(
        selection_head_id=head.id,
        run_id=run.id,
        candidate_id=candidate.id,
        quote_revision_id=quote.id,
        proposal_json=value,
        content_hash=digest(value),
        approval_deadline=min(aware(quote.accept_by), instant(db) + timedelta(days=1)),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    head.current_proposal_id, head.lifecycle_projection, head.proposed_assignment_id = (
        row.id,
        "PENDING_APPROVALS",
        None,
    )
    touch(head)
    record(db, ctx, "TRADETWIN_SELECTION_PROPOSED", row, trade, cn)
    from .persistence import selection_event

    selection_event(db, ctx, row, "PROPOSED", head)
    return {
        "id": row.id,
        "proposal_hash": row.content_hash,
        "quote_hash": quote.content_hash,
        "lifecycle": head.lifecycle_projection,
        "etag": f'"{head.row_version}"',
    }


def approve(db, ctx, ident, payload, role):
    row, head, trade, cn = exact(db, ctx, ident, role)
    from app.operations.access import match

    match(ctx, head)
    current(db, row, head, trade, cn)
    quote = exists(db, Quote, row.quote_revision_id)
    if payload.proposal_hash != row.content_hash or payload.quote_hash != quote.content_hash:
        fail("APPROVAL_HASH_MISMATCH", "Approve the exact proposal and quote hashes.")
    if payload.decision == "APPROVE" and not set(
        row.proposal_json["acknowledged_limitations_required"]
    ) <= set(payload.acknowledged_limitation_codes):
        fail(
            "LIMITATION_ACKNOWLEDGEMENT_REQUIRED",
            "Acknowledge the exact estimate/release limitations.",
        )
    roles = [role]
    value = row.proposal_json
    if (
        role == "PAYER"
        and value["freight_payer_organisation_id"] == value["coordinating_organisation_id"]
    ):
        require(db, ctx.user, ctx.org_id, "tradetwin.plan.apply", trade.id)
        roles.append("COORDINATOR")
    for r in roles:
        existing = db.scalar(
            select(Decision).where(Decision.proposal_id == row.id, Decision.decision_role == r)
        )
        if existing:
            fail(
                "DECISION_ALREADY_RECORDED",
                "Decision is immutable; cancel and repropose for changes.",
            )
        db.add(
            Decision(
                proposal_id=row.id,
                decision_role=r,
                decision=payload.decision,
                proposal_hash=row.content_hash,
                quote_hash=quote.content_hash,
                acknowledged_limitations_json=payload.acknowledged_limitation_codes,
                reason=payload.reason,
                actor_user_id=ctx.user.id,
                actor_organisation_id=ctx.org_id,
            )
        )
    db.flush()
    decisions = {
        d.decision_role: d
        for d in db.scalars(select(Decision).where(Decision.proposal_id == row.id))
    }
    if payload.decision == "REJECT":
        head.lifecycle_projection = "REJECTED"
    elif all(
        r in decisions and decisions[r].decision == "APPROVE" for r in ["PAYER", "COORDINATOR"]
    ):
        assignment = Assignment(
            consignment_id=cn.id,
            carrier_organization_id=value["carrier_organisation_id"],
            vehicle_id=quote.vehicle_id,
            driver_user_id=quote.driver_user_id,
            booking_start_at=aware_from(quote.quote_json["booking_window_start"]),
            booking_end_at=aware_from(quote.quote_json["booking_window_end"]),
            proposed_by_organization_id=cn.coordinating_organization_id,
            created_by=ctx.user.id,
            notes="Exact-hash TradeTwin freight proposal " + row.id,
        )
        db.add(assignment)
        db.flush()
        head.proposed_assignment_id, head.lifecycle_projection = (
            assignment.id,
            "PENDING_CARRIER_ACCEPTANCE",
        )
    touch(head)
    record(db, ctx, "TRADETWIN_" + role + "_DECISION", row, trade, cn)
    from .persistence import selection_event

    selection_event(db, ctx, row, role + "_" + payload.decision, head)
    return {
        "id": row.id,
        "lifecycle": head.lifecycle_projection,
        "proposed_assignment_id": head.proposed_assignment_id,
        "proposal_hash": row.content_hash,
        "quote_hash": quote.content_hash,
        "etag": f'"{head.row_version}"',
    }


def accept(db, ctx, ident, payload):
    row, head, trade, cn = exact(db, ctx, ident, "CARRIER")
    from app.operations.access import match

    match(ctx, head)
    current(db, row, head, trade, cn)
    quote = exists(db, Quote, row.quote_revision_id)
    qhead = exists(db, QuoteHead, quote.quote_head_id)
    if (
        payload.proposal_hash != row.content_hash
        or payload.quote_hash != quote.content_hash
        or str(payload.proposed_assignment_id) != head.proposed_assignment_id
    ):
        fail(
            "APPROVAL_HASH_MISMATCH",
            "Carrier must accept the exact approved offer, route, timing and resources.",
        )
    decisions = {
        d.decision_role: d
        for d in db.scalars(select(Decision).where(Decision.proposal_id == row.id))
    }
    for role, code in [
        ("PAYER", "PAYER_APPROVAL_REQUIRED"),
        ("COORDINATOR", "COORDINATOR_APPROVAL_REQUIRED"),
    ]:
        if (
            role not in decisions
            or decisions[role].decision != "APPROVE"
            or decisions[role].proposal_hash != row.content_hash
            or decisions[role].quote_hash != quote.content_hash
        ):
            fail(code, "Required exact-hash financial/operational approval is missing.")
        # A stored approval is not usable after its actor's capability was revoked.
        from app.trades.models import User

        approver = exists(db, User, decisions[role].actor_user_id)
        if not approver.active:
            fail(code, "Required approving account is inactive.")
        require(
            db,
            approver,
            decisions[role].actor_organisation_id,
            "freight.commit.approve" if role == "PAYER" else "tradetwin.plan.apply",
            trade.id,
        )
    lifecycle, effective = quote_status(db, quote, instant(db))
    if lifecycle != "SUBMITTED" or effective != "CURRENT":
        fail(
            "QUOTE_EXPIRED" if effective != "CURRENT" else "QUOTE_" + lifecycle,
            "Only a current submitted offer can be accepted.",
        )
    if payload.decision == "DECLINE":
        assignment = exists(db, Assignment, head.proposed_assignment_id)
        assignment.status = "DECLINED"
        head.lifecycle_projection = "REJECTED"
        touch(head)
        record(db, ctx, "FREIGHT_OFFER_DECLINED", row, trade, cn)
        return {"id": row.id, "lifecycle": "REJECTED", "etag": f'"{head.row_version}"'}
    if head.current_commitment_id:
        fail("COMMITMENT_ALREADY_ACTIVE", "An active freight commitment already exists.")
    run = exists(db, Run, row.run_id)
    intent = run.input_json["planning_intent"]
    timing = row.proposal_json["selected_timing_snapshot"]
    # Validate selected timing using the existing allocation rules, without a second planner.
    from app.operations.allocation import validate_plan
    from app.operations.quantities import items
    from app.operations.schemas import ConsignmentPlan

    plan = {
        **cn.plan_json,
        "source_accepted_revision_id": trade.accepted_revision_id,
        "coordinating_organization_id": cn.coordinating_organization_id,
        "items": [
            {"line_ref": i.line_ref, "allocated_quantity": str(i.allocated_quantity), "uqc": i.uqc}
            for i in items(db, cn.id)
        ],
        "planned_pickup_start": intent["intended_pickup_at"],
        "planned_pickup_end": timing["estimated_departure_at"],
        "expected_delivery_at": timing["estimated_arrival_at"],
    }
    parsed = ConsignmentPlan.model_validate(plan)
    validate_plan(db, trade, parsed, cn.id)
    previous_defer = db.info.get("defer_compliance_context")
    db.info["defer_compliance_context"] = True
    try:
        cn.plan_json = parsed.model_dump(
            mode="json",
            exclude={"items", "source_accepted_revision_id", "coordinating_organization_id"},
        )
        assignment = transport.decide(
            db,
            ctx,
            head.proposed_assignment_id,
            AssignmentDecision(
                decision="ACCEPT",
                vehicle_id=quote.vehicle_id,
                driver_user_id=quote.driver_user_id,
                reason=payload.reason,
            ),
            freight_selection_id=row.id,
        )
    finally:
        db.info["defer_compliance_context"] = previous_defer
    decision = Decision(
        id=uid(),
        proposal_id=row.id,
        decision_role="CARRIER",
        decision="ACCEPT",
        proposal_hash=row.content_hash,
        quote_hash=quote.content_hash,
        acknowledged_limitations_json=[],
        reason=payload.reason,
        actor_user_id=ctx.user.id,
        actor_organisation_id=ctx.org_id,
    )
    db.add(decision)
    db.flush()
    value = {
        **deepcopy(row.proposal_json),
        "selection_proposal_id": row.id,
        "rfq_id": qhead.rfq_id,
        "payer_decision_id": decisions["PAYER"].id,
        "coordinator_decision_id": decisions["COORDINATOR"].id,
        "carrier_acceptance_event_id": decision.id,
        "accepted_assignment_id": assignment["id"],
        "service_snapshot": quote.quote_json,
        "price_snapshot": {"carrier_payable_total_minor": str(quote.carrier_payable_total_minor)},
        "cancellation_terms_snapshot": quote.quote_json["cancellation_terms"],
        "committed_at": instant(db).isoformat(),
        "limitations_snapshot": POST_SELECTION,
    }
    committed = Commitment(
        selection_proposal_id=row.id,
        trade_id=trade.id,
        consignment_id=cn.id,
        accepted_assignment_id=assignment["id"],
        quote_revision_id=quote.id,
        commitment_json=value,
        content_hash=digest(value),
        execution_mode=trade.execution_mode,
        created_by_user_id=ctx.user.id,
    )
    db.add(committed)
    db.flush()
    route = {
        "freight_commitment_id": committed.id,
        "accepted_assignment_id": assignment["id"],
        "route_snapshot": value["selected_route_snapshot"],
        "routing_vehicle_profile_revision_id": quote.profile_revision_id,
        "pickup_location_revision_id": run.input_json["context"]["pickup_location_revision_id"],
        "drop_location_revision_id": run.input_json["context"]["drop_location_revision_id"],
        "planned_pickup_at": intent["intended_pickup_at"],
        "planned_departure_at": timing["estimated_departure_at"],
        "estimated_arrival_at": timing["estimated_arrival_at"],
        "state_sequence": value["selected_route_snapshot"]["state_sequence"],
    }
    revision = RoutePlan(
        consignment_id=cn.id,
        revision_number=latest_number(db, RoutePlan, RoutePlan.consignment_id == cn.id),
        freight_commitment_id=committed.id,
        accepted_assignment_id=assignment["id"],
        route_plan_json=route,
        content_hash=digest(route),
        created_by_user_id=ctx.user.id,
    )
    db.add(revision)
    db.flush()
    plan_head = db.scalar(select(PlanHead).where(PlanHead.consignment_id == cn.id))
    if not plan_head:
        plan_head = PlanHead(consignment_id=cn.id, created_by=ctx.user.id)
        db.add(plan_head)
    plan_head.current_revision_id = revision.id
    head.current_commitment_id, head.lifecycle_projection = committed.id, "COMMITTED"
    qhead.lifecycle_projection = "ACCEPTED"
    touch(head)
    touch(qhead)
    db.add(
        QuoteEvent(
            quote_revision_id=quote.id,
            event_type="ACCEPTED",
            reason=payload.reason,
            actor_user_id=ctx.user.id,
        )
    )
    db.add(
        CommitmentEvent(
            commitment_id=committed.id,
            event_type="CREATED",
            event_json={"route_plan_id": revision.id},
            reason=payload.reason,
            actor_user_id=ctx.user.id,
        )
    )
    bump_context(db, trade.id, "FREIGHT_PLAN_COMMITTED")
    # Handoff is a draft, not a fact approval or a dispatch evaluation.
    from app.compliance.models import Fact

    old_head = context.heads(db, cn)
    previous = (
        db.get(Fact, old_head.current_fact_revision_id)
        if old_head and old_head.current_fact_revision_id
        else None
    )
    declared = deepcopy(previous.facts_json) if previous else {}
    from app.compliance.schemas_facts import Facts

    declared = {
        k: v for k, v in declared.items() if k in Facts.model_fields and k != "field_provenance"
    }
    declared.update(
        declared_transit_state_codes=route["state_sequence"][1:-1],
        corridor_declaration_basis="SUPPORTED_ROUTE_RECORD",
        requested_pickup_at=route["planned_pickup_at"],
        requested_departure_at=route["planned_departure_at"],
        expected_arrival_at=route["estimated_arrival_at"],
    )
    db.add(
        Fact(
            trade_id=trade.id,
            consignment_id=cn.id,
            revision_number=latest_number(db, Fact, Fact.consignment_id == cn.id),
            accepted_trade_revision_id=trade.accepted_revision_id,
            assignment_id=assignment["id"],
            prepared_context_version=context.version(db, trade.id),
            inherited_hash=digest(context.inherited(db, trade, cn)),
            submitted_for_review=False,
            facts_json=declared,
            provenance_json={
                "handoff": {
                    "origin": "COMMITTED_ROUTE_PLAN",
                    "route_plan_id": revision.id,
                    "content_hash": revision.content_hash,
                }
            },
            content_hash=digest(declared),
            created_by_user_id=ctx.user.id,
        )
    )
    from .persistence import selection_event

    selection_event(db, ctx, row, "COMMITTED", head)
    record(db, ctx, "FREIGHT_PLAN_COMMITTED", committed, trade, cn)
    return {
        "id": row.id,
        "commitment_id": committed.id,
        "accepted_assignment_id": assignment["id"],
        "route_plan_id": revision.id,
        "lifecycle": "COMMITTED",
        "new_context_version": context.version(db, trade.id),
        "dispatch_authorisation": None,
        "permitted_next_actions": POST_SELECTION,
        "etag": f'"{head.row_version}"',
    }


def cancel_selection(db, ctx, ident, payload):
    row, head, trade, cn = exact(db, ctx, ident)
    from app.operations.access import match

    match(ctx, head)
    if head.current_proposal_id != row.id or head.current_commitment_id:
        fail(
            "COMMITMENT_CANCELLATION_REQUIRED",
            "Use bilateral cancellation for an active priced commitment.",
        )
    if head.proposed_assignment_id:
        assignment = exists(db, Assignment, head.proposed_assignment_id)
        if assignment.status == "PROPOSED":
            assignment.status = "CANCELLED"
            touch(assignment)
    head.lifecycle_projection = "CANCELLED"
    touch(head)
    record(db, ctx, "TRADETWIN_SELECTION_CANCELLED", row, trade, cn)
    from .persistence import selection_event

    selection_event(db, ctx, row, "CANCELLED", head)
    return {"id": row.id, "lifecycle": "CANCELLED", "etag": f'"{head.row_version}"'}


def propose_cancellation(db, ctx, ident, payload):
    row = exists(db, Commitment, ident)
    trade, cn = planning(db, ctx, row.consignment_id, "freight.commit.approve", True)
    if ctx.org_id != row.commitment_json["freight_payer_organisation_id"]:
        fail("FORBIDDEN", "Only the freight payer proposes cancellation terms.", status=403)
    before_pickup(cn)
    if row.content_hash != payload.commitment_hash:
        fail("APPROVAL_HASH_MISMATCH", "Cancellation must bind the original commitment.")
    value = {**payload.model_dump(mode="json"), "commitment_id": row.id}
    result = Cancellation(
        commitment_id=row.id,
        commitment_hash=row.content_hash,
        cancellation_json=value,
        proposal_hash=digest(value),
        created_by=ctx.user.id,
    )
    db.add(result)
    db.add(
        CommitmentEvent(
            commitment_id=row.id,
            event_type="CANCELLATION_REQUESTED",
            event_json={"proposal_hash": result.proposal_hash},
            reason=payload.reason,
            actor_user_id=ctx.user.id,
        )
    )
    record(db, ctx, "FREIGHT_CANCELLATION_PROPOSED", result, trade, cn)
    return view(result)


def cancel_commitment(db, ctx, ident, payload):
    row = exists(db, Cancellation, ident)
    committed = exists(db, Commitment, row.commitment_id)
    trade = lock_trade(db, committed.trade_id)
    cn = exists(db, Consignment, committed.consignment_id)
    db.refresh(row)
    db.refresh(cn)
    before_pickup(cn)
    from app.operations.access import match

    match(ctx, row)
    if row.status != "PENDING" or payload.proposal_hash != row.proposal_hash:
        fail("APPROVAL_HASH_MISMATCH", "Cancellation proposal is not current.")
    required = {
        "PAYER": (
            committed.commitment_json["freight_payer_organisation_id"],
            "freight.commit.approve",
        ),
        "COORDINATOR": (cn.coordinating_organization_id, "tradetwin.plan.apply"),
        "CARRIER": (committed.commitment_json["carrier_organisation_id"], "freight.offer.accept"),
    }
    org, permission = required[payload.decision_role]
    if ctx.org_id != org:
        fail("FORBIDDEN", "Only the responsible organisation decides cancellation.", status=403)
    require(db, ctx.user, ctx.org_id, permission, trade.id)
    db.add(
        CancellationDecision(
            cancellation_proposal_id=row.id,
            decision_role=payload.decision_role,
            decision=payload.decision,
            proposal_hash=row.proposal_hash,
            reason=payload.reason,
            actor_user_id=ctx.user.id,
            actor_organisation_id=ctx.org_id,
        )
    )
    db.flush()
    votes = {
        d.decision_role: d
        for d in db.scalars(
            select(CancellationDecision).where(
                CancellationDecision.cancellation_proposal_id == row.id
            )
        )
    }
    if payload.decision == "REJECT":
        row.status = "REJECTED"
    elif all(
        r in votes and votes[r].decision == "APPROVE"
        for r in required
        if r != "COORDINATOR"
        or cn.coordinating_organization_id
        != committed.commitment_json["freight_payer_organisation_id"]
    ):
        from app.trades.models import User

        for role, decision in votes.items():
            approver = exists(db, User, decision.actor_user_id)
            if not approver.active:
                fail("APPROVAL_REVOKED", "A cancellation approver is inactive.")
            require(db, approver, decision.actor_organisation_id, required[role][1], trade.id)
        head = db.scalar(select(SelectionHead).where(SelectionHead.consignment_id == cn.id))
        if (
            head.current_commitment_id != committed.id
            or cn.active_assignment_id != committed.accepted_assignment_id
        ):
            fail("RUN_STALE", "Active commitment/assignment changed.")
        assignment = exists(db, Assignment, committed.accepted_assignment_id)
        assignment.status = "CANCELLED"
        touch(assignment)
        for booking in db.scalars(
            select(Booking).where(
                Booking.assignment_id == assignment.id, Booking.released_at.is_(None)
            )
        ):
            booking.released_at = instant(db)
            from .persistence import resource_changed

            resource_changed(db, trade.execution_mode, booking.resource_type, booking.resource_id)
        cn.active_assignment_id = None
        touch(cn)
        head.current_commitment_id, head.lifecycle_projection = None, "CANCELLED"
        touch(head)
        route_head = db.scalar(select(PlanHead).where(PlanHead.consignment_id == cn.id))
        route_head.current_revision_id = None
        touch(route_head)
        row.status = "AGREED"
        db.add(
            CommitmentEvent(
                commitment_id=committed.id,
                event_type="CANCELLED",
                event_json=row.cancellation_json,
                reason=payload.reason,
                actor_user_id=ctx.user.id,
            )
        )
        bump_context(db, trade.id, "FREIGHT_PLAN_CANCELLED")
    touch(row)
    record(db, ctx, "FREIGHT_CANCELLATION_DECIDED", row, trade, cn)
    return {**view(row), "payment_created": False, "refund_created": False}


def guard_manual_change(db, cn):
    from sqlalchemy import inspect

    if not inspect(db.get_bind()).has_table(SelectionHead.__tablename__):
        return
    head = db.scalar(select(SelectionHead).where(SelectionHead.consignment_id == cn.id))
    if head and head.current_commitment_id:
        fail(
            "COMMITMENT_CANCELLATION_REQUIRED",
            "Cancel the active priced commitment bilaterally before incompatible manual changes.",
        )


def abort_service(db, ctx, cn):
    head = db.scalar(select(SelectionHead).where(SelectionHead.consignment_id == cn.id))
    if head and head.current_commitment_id:
        db.add(
            CommitmentEvent(
                commitment_id=head.current_commitment_id,
                event_type="SERVICE_ABORTED",
                event_json={"consignment_id": cn.id, "financial_obligations": "UNRESOLVED"},
                reason="Consignment independently cancelled; no payment/refund inferred",
                actor_user_id=ctx.user.id,
            )
        )


def phase4_dependency(db, cn):
    from sqlalchemy import inspect

    if not inspect(db.get_bind()).has_table(PlanHead.__tablename__):
        return None
    head = db.scalar(select(PlanHead).where(PlanHead.consignment_id == cn.id))
    if not head or not head.current_revision_id:
        return None
    plan = exists(db, RoutePlan, head.current_revision_id)
    from .models import Dataset, DatasetEvent, LocationHead, Profile, Template

    loc = db.scalar(select(LocationHead).where(LocationHead.consignment_id == cn.id))
    profile = exists(db, Profile, plan.route_plan_json["routing_vehicle_profile_revision_id"])
    from app.operations.models import Vehicle

    vehicle = exists(db, Vehicle, profile.vehicle_id)
    committed = exists(db, Commitment, plan.freight_commitment_id)
    quote = exists(db, Quote, committed.quote_revision_id)
    dataset = exists(
        db, Dataset, exists(db, Template, quote.route_template_revision_id).dataset_revision_id
    )
    publication = db.scalar(
        select(DatasetEvent)
        .where(
            DatasetEvent.dataset_revision_id == dataset.id,
            DatasetEvent.event_type.in_(["PUBLISHED", "SUSPENDED"]),
        )
        .order_by(DatasetEvent.created_at.desc(), DatasetEvent.id.desc())
    )
    from .routing import dataset_current

    return {
        "id": plan.id,
        "hash": plan.content_hash,
        "plan": plan.route_plan_json,
        "current_profile_id": vehicle.current_routing_profile_revision_id,
        "current_pickup_location_id": loc.pickup_location_revision_id if loc else None,
        "current_drop_location_id": loc.drop_location_revision_id if loc else None,
        "dataset_hash": dataset.content_hash,
        "dataset_publication_event_id": publication.id if publication else None,
        "dataset_current": dataset_current(
            db, dataset, instant(db), aware_from(plan.route_plan_json["estimated_arrival_at"])
        ),
    }


def plan_valid(db, trade, cn, facts, at):
    dependency = phase4_dependency(db, cn)
    if dependency is None:
        return True
    plan = dependency["plan"]
    if (
        plan["accepted_assignment_id"] != cn.active_assignment_id
        or plan["routing_vehicle_profile_revision_id"] != dependency["current_profile_id"]
    ):
        return False
    if (
        plan["pickup_location_revision_id"] != dependency["current_pickup_location_id"]
        or plan["drop_location_revision_id"] != dependency["current_drop_location_id"]
    ):
        return False
    corridor = [
        cn.pickup_address_snapshot["state_code"],
        *(facts.get("declared_transit_state_codes") or []),
        cn.delivery_address_snapshot["state_code"],
    ]
    if (
        corridor != plan["state_sequence"]
        or not facts.get("expected_arrival_at")
        or aware_from(facts["expected_arrival_at"]) != aware_from(plan["estimated_arrival_at"])
    ):
        return False
    committed = exists(db, Commitment, plan["freight_commitment_id"])
    quote = exists(db, Quote, committed.quote_revision_id)
    from .models import Dataset, Template
    from .routing import dataset_current

    dataset = exists(
        db, Dataset, exists(db, Template, quote.route_template_revision_id).dataset_revision_id
    )
    return dataset_current(db, dataset, at, aware_from(plan["estimated_arrival_at"]))
