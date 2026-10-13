"""Frozen decision inputs on the existing durable job/outbox pipeline."""

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.compliance import context, governance, inputs
from app.compliance.clock import aware, instant
from app.compliance.expression import evaluate
from app.compliance.models import Rule, TransportEvidence, TransportReview
from app.document_desk.models import Job, Outbox
from app.operations.access import aligned, before_pickup, exists, fail
from app.operations.ledger import record
from app.operations.models import Booking, Vehicle
from app.trades.access import grants, membership
from app.trades.errors import TradeError
from app.trades.models import Revision, User, uid
from app.trades.terms import digest

from .access import base_context, planning
from .assessment import assess
from .calculator import ENGINE_VERSION, rank
from .models import (
    RFQ,
    AssumptionReview,
    Assumptions,
    Candidate,
    Dataset,
    Location,
    Profile,
    Quote,
    QuoteHead,
    ResourceVersion,
    Run,
    Template,
)
from .offers import quote_status
from .routing import aware_from, dataset_current
from .schemas import RunInput

BASE = {
    "scenario_code": "BASE",
    "label": "Base plan",
    "delay_placement": "ORIGIN_BEFORE_DEPARTURE",
    "additional_wait_minutes": 0,
    "additional_stop_minutes": 0,
    "assumption_origin": "PUBLISHED_QUOTE_TERM",
    "assumption_note": None,
}


def dependencies(db, trade, cn, quote_ids, assumption_id, at=None):
    at = at or instant(db)
    quotes = []
    for ident in quote_ids:
        quote = exists(db, Quote, ident)
        head = exists(db, QuoteHead, quote.quote_head_id)
        vehicle = exists(db, Vehicle, quote.vehicle_id)
        template = exists(db, Template, quote.route_template_revision_id)
        dataset = exists(db, Dataset, template.dataset_revision_id)
        driver = exists(db, User, quote.driver_user_id)
        try:
            driver_grants = [
                g.id
                for g in grants(db, membership(db, driver, head.carrier_organisation_id), trade.id)
                if g.permission_code == "shipment.event.record" and g.capability == "DRIVER"
            ]
        except TradeError:
            driver_grants = []
        versions = {
            kind: version.version
            if (version := db.get(ResourceVersion, (trade.execution_mode, kind, resource)))
            else 0
            for kind, resource in [("VEHICLE", quote.vehicle_id), ("DRIVER", quote.driver_user_id)]
        }
        evidence = []
        for ident in quote.quote_json["transport_evidence_revision_ids"]:
            ev = exists(db, TransportEvidence, ident)
            reviewed = db.scalar(
                select(TransportReview)
                .where(TransportReview.evidence_revision_id == ev.id)
                .order_by(TransportReview.created_at.desc(), TransportReview.id.desc())
            )
            evidence.append(
                {
                    "id": ev.id,
                    "hash": ev.content_hash,
                    "review": reviewed.id if reviewed else None,
                    "source": context.source_state(db, ev.document_version_id)
                    if ev.document_version_id
                    else None,
                }
            )
        availability = list(
            db.scalars(
                select(Booking)
                .where(
                    Booking.resource_id.in_([quote.vehicle_id, quote.driver_user_id]),
                    Booking.released_at.is_(None),
                    Booking.booking_start_at < aware_from(quote.quote_json["booking_window_end"]),
                    Booking.booking_end_at > aware_from(quote.quote_json["booking_window_start"]),
                    Booking.assignment_id != (cn.active_assignment_id or uid()),
                )
                .order_by(Booking.id)
            )
        )
        quotes.append(
            {
                "id": quote.id,
                "hash": quote.content_hash,
                "head": head.current_revision_id,
                "lifecycle": head.lifecycle_projection,
                "profile_head": vehicle.current_routing_profile_revision_id,
                "vehicle": vehicle.vehicle_json,
                "vehicle_active": vehicle.active,
                "driver_active": driver.active,
                "driver_grants": sorted(driver_grants),
                "resource_versions": versions,
                "dataset_hash": dataset.content_hash,
                "dataset_current": dataset_current(db, dataset, at),
                "evidence": evidence,
                "availability_hash": digest([b.id for b in availability]),
            }
        )
    assumptions = exists(db, Assumptions, assumption_id) if assumption_id else None
    review = (
        db.scalar(
            select(AssumptionReview)
            .where(AssumptionReview.assumption_revision_id == assumptions.id)
            .order_by(AssumptionReview.created_at.desc(), AssumptionReview.id.desc())
        )
        if assumptions
        else None
    )
    return {
        "context_hash": base_context(db, trade, cn)["planning_context_hash"],
        "quotes": quotes,
        "assumptions_hash": assumptions.content_hash if assumptions else None,
        "assumption_review_id": review.id if review else None,
        "engine": ENGINE_VERSION,
    }


def fresh(db, row, trade, cn, at=None):
    at = at or instant(db)
    snapshot = row.input_json
    if (
        digest(
            dependencies(
                db,
                trade,
                cn,
                snapshot["quote_revision_ids"],
                snapshot["cost_assumption_revision_id"],
                at,
            )
        )
        != snapshot["dependency_hash"]
    ):
        return "STALE"
    if any(
        not aware_from(s["quote"]["valid_from"]) <= at < aware_from(s["quote"]["accept_by"])
        or not dataset_current(db, exists(db, Dataset, s["template"]["dataset_revision_id"]), at)
        for s in snapshot["sources"]
    ):
        return "STALE"
    if any(
        at >= aware_from(ref["valid_until"])
        for source in snapshot["sources"]
        for ref in source["permit_coverage"]["source_refs"]
    ):
        return "STALE"
    if any(
        c.get("valid_until") and at >= aware_from(c["valid_until"])
        for c in (snapshot["cost_assumptions"] or {}).get("external_cost_components", [])
    ):
        return "STALE"
    return "CURRENT"


def permit_snapshot(db, quote, through, at):
    kinds, refs = {}, []
    for ident in quote.quote_json["transport_evidence_revision_ids"]:
        ev = exists(db, TransportEvidence, ident)
        if (
            ev.evidence_type not in {"GOODS_PERMIT", "PERMIT_AUTHORISATION"}
            or ev.subject_id != quote.vehicle_id
        ):
            continue
        rev = db.scalar(
            select(TransportReview)
            .where(TransportReview.evidence_revision_id == ev.id)
            .order_by(TransportReview.created_at.desc(), TransportReview.id.desc())
        )
        data = ev.evidence_json
        if (
            not rev
            or rev.decision != "APPROVE_DECLARATION"
            or not ev.document_version_id
            or data.get("source_mode") == "SELF_DECLARATION"
        ):
            continue
        source = context.source_state(db, ev.document_version_id)
        if (
            not source
            or source.get("lifecycle_status") != "ACTIVE"
            or source.get("current_version_id") != ev.document_version_id
            or source.get("current_fact_revision_id") != ev.reviewed_fact_revision_id
            or any(
                a["security_state"] != "CLEAN" or a["expected_hash"] != a["current_hash"]
                for a in source.get("assets", [])
            )
        ):
            continue
        if (
            data.get("covered_vehicle_number")
            != quote.quote_json["vehicle_snapshot"]["registration_number"]
            or not data.get("valid_from")
            or not data.get("valid_until")
            or not aware_from(data["valid_from"]) <= at < through < aware_from(data["valid_until"])
        ):
            continue
        if data.get("route_restriction_position") != "NONE_DECLARED" or data.get(
            "route_restrictions"
        ):
            continue
        if data.get("source_mode") in {"AUTHORISED_LOOKUP", "ISSUER_DIGITAL_RECORD"}:
            from app.document_desk.models import VerificationResult

            observed = (
                db.get(VerificationResult, ev.verification_result_id)
                if ev.verification_result_id
                else None
            )
            value = observed.result_json if observed else {}
            if (
                not value.get("fresh_until")
                or at >= aware_from(value["fresh_until"])
                or value.get("normalised_result", {}).get("status") != "ACTIVE"
            ):
                continue
        kinds[ev.evidence_type] = (set(data.get("covered_states", [])), ev)
        refs.append(
            {
                "evidence_revision_id": ev.id,
                "source_version_id": ev.document_version_id,
                "review_id": rev.id,
                "valid_until": data["valid_until"],
            }
        )
    states = None
    if {"GOODS_PERMIT", "PERMIT_AUTHORISATION"} <= kinds.keys():
        permit, auth = kinds["GOODS_PERMIT"], kinds["PERMIT_AUTHORISATION"]
        if auth[1].parent_permit_evidence_revision_id == permit[1].id:
            states = sorted(permit[0] & auth[0])
    return {"covered_states": states, "source_refs": refs}


def request(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.run", True)
    if (
        ctx.if_match != f'"{context.version(db, trade.id)}"'
        or payload.expected_context_version != context.version(db, trade.id)
    ):
        fail(
            "RUN_STALE",
            "Reload the current compliance context before running.",
            status=412,
            details={"current_context_version": context.version(db, trade.id)},
        )
    before_pickup(cn)
    aligned(cn)
    base = base_context(db, trade, cn)
    at = instant(db)
    if not base["pickup_location_revision_id"] or not base["drop_location_revision_id"]:
        fail("ROUTING_INPUT_MISSING", "Confirm pickup and drop pins first.")
    assumption = (
        exists(db, Assumptions, payload.cost_assumption_revision_id)
        if payload.cost_assumption_revision_id
        else None
    )
    if assumption and (
        assumption.consignment_id != cn.id
        or assumption.owner_organisation_id != base["freight_payer_organisation_id"]
    ):
        fail("NOT_FOUND", "Cost assumptions not found.", status=404)
    if payload.parent_run_id:
        parent = exists(db, Run, payload.parent_run_id)
        if parent.consignment_id != cn.id:
            fail("NOT_FOUND", "Parent run not found.", status=404)
    deadline = (
        db.get(Revision, trade.accepted_revision_id)
        .facts_json["delivery_requirements"]
        .get("delivery_deadline_at")
    )
    basis = "ACCEPTED_TRADE_TERM" if deadline else "NONE"
    if payload.planning_intent.required_arrival_by and (
        not deadline or payload.planning_intent.required_arrival_by < aware_from(deadline)
    ):
        deadline, basis = payload.planning_intent.required_arrival_by.isoformat(), "RFQ_REQUIREMENT"
    packs, registry, _ = governance.resolve(db, trade.execution_mode, at)
    snapshot = {
        **payload.model_dump(mode="json"),
        "schema_version": "TRADETWIN_INPUT_V1",
        "context": base,
        "deadline": {
            "at": deadline,
            "basis": basis,
            "source_reference": {"accepted_revision_id": trade.accepted_revision_id}
            if basis == "ACCEPTED_TRADE_TERM"
            else None,
        },
        "registry_manifest": registry,
        "cost_assumptions": assumption.assumptions_json if assumption else None,
        "evaluated_as_of": at.isoformat(),
        "sources": [],
    }
    scenarios = [
        BASE,
        *[s.model_dump(mode="json") for s in payload.scenarios if s.scenario_code != "BASE"],
    ]
    snapshot["scenarios"] = scenarios
    for ident in payload.quote_revision_ids:
        quote = exists(db, Quote, ident)
        rfq = exists(db, RFQ, exists(db, QuoteHead, quote.quote_head_id).rfq_id)
        if rfq.consignment_id != cn.id or quote.route_template_revision_id not in [
            str(i) for i in payload.route_template_revision_ids
        ]:
            fail("NOT_FOUND", "Quote/route combination not found.", status=404)
        if quote.source_context_hash != base["planning_context_hash"]:
            fail(
                "QUOTE_CONTEXT_STALE",
                "Offer context differs from current accepted routing/cargo facts.",
            )
        profile = exists(db, Profile, quote.profile_revision_id)
        vehicle = exists(db, Vehicle, quote.vehicle_id)
        template = exists(db, Template, quote.route_template_revision_id)
        dataset = exists(db, Dataset, template.dataset_revision_id)
        if (
            dataset.execution_mode != trade.execution_mode
            or vehicle.execution_mode != trade.execution_mode
        ):
            fail("MODE_MISMATCH", "Inputs and resources must inherit the trade's environment.")
        data, rules, scope = {"facts": {}, "proof": {}, "inherited": {}}, [], False
        supported_corridors = []
        profile_scope = None
        if len(packs) == 1:
            pack = packs[0]
            supported_corridors = pack.policy_json["supported_corridors"]
            data, _, _ = inputs.prepare(db, trade, cn, pack, "PICKUP_CONFIRMED", at)
            scope = (
                evaluate(pack.supported_scope_json, data) is True
                and evaluate(pack.excluded_scope_json, data) is False
            )
            declared = data["facts"]
            if declared.get("scope_profile_code") is not None and declared.get(
                "commodity_scope_codes"
            ):
                profile_scope = declared["scope_profile_code"] in pack.policy_json[
                    "supported_scope_codes"
                ] and set(declared["commodity_scope_codes"]) <= set(
                    pack.policy_json["supported_commodity_codes"]
                )
            rules = [
                r.rule_json
                for r in db.scalars(
                    select(Rule).where(Rule.pack_revision_id == pack.id).order_by(Rule.rule_code)
                )
            ]
        source = {
            "quote_revision_id": quote.id,
            "quote_hash": quote.content_hash,
            "quote": quote.quote_json,
            "quote_lifecycle": quote_status(db, quote, at)[0],
            "profile": profile.profile_json,
            "profile_hash": profile.content_hash,
            "profile_current": vehicle.current_routing_profile_revision_id == profile.id
            and vehicle.active
            and vehicle.vehicle_json == profile.profile_json["vehicle_declarations"],
            "template": template.template_json,
            "template_hash": template.content_hash,
            "dataset": dataset.dataset_json,
            "dataset_current": dataset_current(
                db, dataset, at, payload.planning_intent.intended_departure_at
            ),
            "pickup_location": exists(
                db, Location, base["pickup_location_revision_id"]
            ).location_json,
            "drop_location": exists(db, Location, base["drop_location_revision_id"]).location_json,
            "permit_coverage": permit_snapshot(
                db, quote, payload.planning_intent.intended_departure_at, at
            ),
            "compliance_inputs": data,
            "compliance_rules": rules,
            "compliance_scope_supported": scope,
            "compliance_supported_corridors": supported_corridors,
            "compliance_profile_supported": profile_scope,
            "document_planning_deadlines": data.get("authority_deadlines", []),
            "scenario_hashes": {s["scenario_code"]: digest(s) for s in scenarios},
            "resource_available": not bool(
                db.scalar(
                    select(Booking.id).where(
                        Booking.resource_id.in_([quote.vehicle_id, quote.driver_user_id]),
                        Booking.released_at.is_(None),
                        Booking.assignment_id != (cn.active_assignment_id or uid()),
                        Booking.booking_start_at
                        < aware_from(quote.quote_json["booking_window_end"]),
                        Booking.booking_end_at
                        > aware_from(quote.quote_json["booking_window_start"]),
                    )
                )
            ),
        }
        snapshot["sources"].append(source)
    snapshot["dependency_hash"] = digest(
        dependencies(
            db,
            trade,
            cn,
            snapshot["quote_revision_ids"],
            snapshot["cost_assumption_revision_id"],
            at,
        )
    )
    row = Run(
        id=uid(),
        trade_id=trade.id,
        consignment_id=cn.id,
        owner_organisation_id=ctx.org_id,
        parent_run_id=str(payload.parent_run_id) if payload.parent_run_id else None,
        execution_mode=trade.execution_mode,
        input_json=snapshot,
        content_hash=digest(snapshot),
        engine_version=ENGINE_VERSION,
        evaluated_as_of=at,
        created_by_user_id=ctx.user.id,
    )
    existing = db.scalar(
        select(Run).where(
            Run.content_hash == row.content_hash, Run.owner_organisation_id == ctx.org_id
        )
    )
    if existing:
        return {
            "run_id": existing.id,
            "job_state": existing.job_state,
            "input_hash": existing.content_hash,
            "evaluated_as_of": aware(existing.evaluated_as_of).isoformat(),
        }
    db.add(row)
    db.flush()
    from .models import RunDependency

    db.add(
        RunDependency(
            run_id=row.id,
            dependency_type="EXACT_PLANNING_CONTEXT",
            entity_id=cn.id,
            content_hash=snapshot["dependency_hash"],
            dependency_json=dependencies(
                db,
                trade,
                cn,
                snapshot["quote_revision_ids"],
                snapshot["cost_assumption_revision_id"],
                at,
            ),
        )
    )
    job = Job(
        trade_id=trade.id,
        stage="TRADETWIN_RUN",
        input_fingerprint=digest({"run_id": row.id, "input_hash": row.content_hash}),
        pipeline_version=ENGINE_VERSION,
        schema_version="TRADETWIN_INPUT_V1",
        configuration_hash=digest(registry),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"run_id": row.id, "consignment_id": cn.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    row.job_id = job.id
    db.add(Outbox(job_id=job.id))
    record(db, ctx, "TRADETWIN_RUN_QUEUED", row, trade, cn)
    return {
        "run_id": row.id,
        "job_state": row.job_state,
        "input_hash": row.content_hash,
        "evaluated_as_of": at.isoformat(),
    }


def complete(db, ctx, ident):
    row = exists(db, Run, ident)
    trade, cn = planning(db, ctx, row.consignment_id, "tradetwin.run", True)
    if row.job_state in {"COMPLETED", "FAILED", "CANCELLED"}:
        return
    snapshot = row.input_json
    candidates = []
    for source in snapshot["sources"]:
        ident = str(uuid5(NAMESPACE_URL, row.content_hash + ":" + source["quote_revision_id"]))
        scenarios = {
            s["scenario_code"]: assess(snapshot, source, s, ident) for s in snapshot["scenarios"]
        }
        base = scenarios["BASE"]
        value = {
            "candidate_id": ident,
            "offer_label": source["quote"].get("carrier_offer_reference")
            or source["quote_revision_id"][:8],
            "quote_revision_id": source["quote_revision_id"],
            "quote_hash": source["quote_hash"],
            "route_template_revision_id": source["quote"]["route_template_revision_id"],
            "carrier_organisation_id": source["quote"]["carrier_organisation_id"],
            "vehicle_id": source["quote"]["vehicle_id"],
            "scenarios": scenarios,
            "execution_mode": row.execution_mode,
        }
        fingerprint = digest(value)
        value["candidate_hash"] = fingerprint
        candidate = Candidate(
            id=ident,
            run_id=row.id,
            quote_revision_id=source["quote_revision_id"],
            route_template_revision_id=source["quote"]["route_template_revision_id"],
            candidate_json=value,
            content_hash=fingerprint,
            planning_outcome=base["planning_outcome"],
            cost_completeness=base["cost"]["cost_completeness"],
            ranking_eligibility=base["ranking_eligibility"],
            created_by_user_id=ctx.user.id,
        )
        db.add(candidate)
        candidates.append(value)
    rankings = {
        s["scenario_code"]: {
            objective: rank(candidates, s["scenario_code"], objective, snapshot["balanced_weights"])
            for objective in ["LOWEST_COMPARABLE_COST", "EARLIEST_ESTIMATED_ARRIVAL", "BALANCED"]
        }
        for s in snapshot["scenarios"]
    }
    result = {
        "schema_version": "TRADETWIN_RESULT_V1",
        "candidates": candidates,
        "rankings": rankings,
        "objective": snapshot["objective"],
        "candidate_count": len(candidates),
        "rankable_candidate_count": sum(
            c["scenarios"]["BASE"]["ranking_eligibility"] == "RANKABLE" for c in candidates
        ),
        "freshness_at_completion": fresh(db, row, trade, cn),
        "ranking_policy_version": "EXACT_COST_TIME_1",
        "limitations": [
            "Lowest estimated comparable logistics cost among these candidates.",
            "Hashing establishes content integrity, not source truth.",
        ],
    }
    cheapest = rankings["BASE"]["LOWEST_COMPARABLE_COST"]
    fastest = rankings["BASE"]["EARLIEST_ESTIMATED_ARRIVAL"]
    result["pareto_frontier"] = [r["candidate_id"] for r in cheapest if r["pareto_member"]]
    if cheapest and fastest:
        by_id = {c["candidate_id"]: c for c in candidates}
        low, early = by_id[cheapest[0]["candidate_id"]], by_id[fastest[0]["candidate_id"]]
        difference = int(early["scenarios"]["BASE"]["cost"]["comparison_total_minor"]) - int(
            low["scenarios"]["BASE"]["cost"]["comparison_total_minor"]
        )
        result["eligible_baseline_comparison"] = {
            "lowest_cost_candidate_id": low["candidate_id"],
            "earliest_arrival_candidate_id": early["candidate_id"],
            "lowest_cost_offer": low["offer_label"],
            "baseline_offer": early["offer_label"],
            "additional_cost_for_earlier_arrival_minor": str(difference),
            "basis": "Gross comparable outlay among eligible candidates; not market-wide savings.",
        }
    row.result_json, row.result_hash = result, digest(result)
    from .persistence import result_rows

    result_rows(db, candidates, rankings, row.id)
    row.job_state, row.completed_at = "COMPLETED", instant(db)
    record(db, ctx, "TRADETWIN_RUN_COMPLETED", row, trade, cn)


def scenario_run(db, ctx, ident, payload):
    parent = exists(db, Run, ident)
    trade, cn = planning(db, ctx, parent.consignment_id, "tradetwin.run", True)
    if fresh(db, parent, trade, cn) != "CURRENT":
        fail("RUN_STALE", "Create a fresh BASE run before stress comparisons.")
    keys = RunInput.model_fields.keys()
    data = {k: deepcopy(v) for k, v in parent.input_json.items() if k in keys}
    data.update(
        parent_run_id=parent.id,
        scenarios=[payload.scenario.model_dump(mode="json")],
        objective=payload.objective,
        balanced_weights=payload.balanced_weights.model_dump(),
    )
    return request(db, ctx, cn.id, RunInput.model_validate(data))


def cancel(db, ctx, ident, payload):
    row = exists(db, Run, ident)
    trade, cn = planning(db, ctx, row.consignment_id, "tradetwin.run", True)
    if row.job_state not in {"QUEUED", "RUNNING"}:
        fail("JOB_ALREADY_TERMINAL", "Only queued/running work can be cancelled.")
    row.job_state = "CANCELLED"
    job = exists(db, Job, row.job_id)
    job.status, job.cancelled_at = "CANCELLED", instant(db)
    record(db, ctx, "TRADETWIN_RUN_CANCELLED", row, trade, cn)
    return {"id": row.id, "job_state": "CANCELLED"}
