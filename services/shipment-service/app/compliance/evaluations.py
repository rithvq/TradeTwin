"""Durable asynchronous deterministic evaluations and live dependency currency."""

from datetime import timedelta

from sqlalchemy import select

from app.document_desk.models import Job, Outbox
from app.operations.access import exists, fail
from app.trades.terms import digest

from . import context, governance, inputs, public_records, recipient
from .clock import aware, instant
from .expression import ENGINE_VERSION, evaluate
from .ledger import check_context, record, view
from .models import (
    Binding,
    CaseAction,
    Dependency,
    Evaluation,
    Packet,
    PacketAck,
    ReleaseReview,
    Requirement,
    ReviewCase,
    Rule,
)


def request(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "compliance.evaluate", True, True)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    _, registry, _ = governance.resolve(db, trade.execution_mode)
    snapshot, fingerprint = context.dependency_snapshot(db, trade, cn, registry)
    head = context.heads(db, cn, True)
    row = Evaluation(
        trade_id=trade.id,
        consignment_id=cn.id,
        action=payload.action,
        execution_mode=trade.execution_mode,
        context_version=context.version(db, trade.id),
        binding_revision_id=head.current_binding_revision_id,
        loading_manifest_revision_id=head.current_loading_manifest_revision_id,
        dependency_hash=fingerprint,
        registry_manifest_json=registry,
        snapshot_json=snapshot,
        engine_version=ENGINE_VERSION,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    job = Job(
        trade_id=trade.id,
        stage="EVAL_COMPLIANCE",
        input_fingerprint=digest({"evaluation_id": row.id, "dependency_hash": fingerprint}),
        pipeline_version=ENGINE_VERSION,
        schema_version="COMPLIANCE_FACTS_V1",
        configuration_hash=digest(registry),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"evaluation_id": row.id, "consignment_id": cn.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    row.job_id = job.id
    db.add(Outbox(job_id=job.id))
    setattr(
        head,
        "current_pickup_evaluation_id"
        if payload.action == "PICKUP_CONFIRMED"
        else "current_departure_evaluation_id",
        row.id,
    )
    record(db, ctx, "COMPLIANCE_EVALUATION_QUEUED", row)
    return {
        "evaluation_id": row.id,
        "job_state": row.job_state,
        "context_version": row.context_version,
        "dependency_hash": fingerprint,
    }


def current(db, row, trade, cn, at=None):
    at = at or instant(db)
    _, registry, _ = governance.resolve(db, trade.execution_mode, at)
    _, fingerprint = context.dependency_snapshot(db, trade, cn, registry)
    if row.dependency_hash != fingerprint or row.execution_mode != trade.execution_mode:
        return "STALE"
    if row.valid_until is not None and at >= aware(row.valid_until):
        return "EXPIRED"
    return "CURRENT"


def exact(db, ctx, ident, permission="compliance.read", seller=False):
    row = exists(db, Evaluation, ident)
    trade, cn, side = context.access(db, ctx, row.consignment_id, permission, seller, True)
    return row, trade, cn, side


def complete(db, ctx, ident):
    row, trade, cn, _ = exact(db, ctx, ident, "compliance.evaluate", True)
    if row.job_state not in {"QUEUED", "RUNNING"}:
        fail("JOB_ALREADY_TERMINAL", "Evaluation already completed.")
    at = instant(db)
    packs, registry, boundary = governance.resolve(db, trade.execution_mode, at)
    _, fingerprint = context.dependency_snapshot(db, trade, cn, registry)
    deadline = at + timedelta(seconds=900)
    row.evaluated_at = at
    row.limitations_json = [
        "Platform dispatch authorisation is not government clearance.",
        "No tax rates, classification, route, freight price "
        "or government registration is certified.",
    ]
    if fingerprint != row.dependency_hash:
        row.job_state, row.decision = "COMPLETED_STALE", "BLOCKED"
        row.limitations_json += [
            "Inputs changed while this evaluation was queued. Submit a fresh evaluation."
        ]
    elif len(packs) != 1:
        row.job_state, row.decision = "COMPLETED", "UNSUPPORTED"
        row.limitations_json += [
            "Exactly one effective independently published pack is required; "
            "absent, suspended or overlapping packs cannot authorise dispatch."
        ]
    else:
        pack = packs[0]
        data, deadlines, dimensions = inputs.prepare(db, trade, cn, pack, row.action, at)
        scope = evaluate(pack.supported_scope_json, data)
        excluded = evaluate(pack.excluded_scope_json, data)
        state = pack.policy_json
        facts = data["facts"]
        corridor = [
            data["inherited"]["origin_state_code"],
            *(facts.get("declared_transit_state_codes") or []),
            data["inherited"]["destination_state_code"],
        ]
        profile_known = (
            facts.get("scope_profile_code") is not None
            and bool(facts.get("commodity_scope_codes"))
            and facts.get("declared_transit_state_codes") is not None
        )
        supported_profile = (
            profile_known
            and facts["scope_profile_code"] in state["supported_scope_codes"]
            and set(facts["commodity_scope_codes"]) <= set(state["supported_commodity_codes"])
            and corridor in state["supported_corridors"]
        )
        from app.freight.commitments import plan_valid

        supported_profile = supported_profile and plan_valid(db, trade, cn, facts, at)
        data["proof"]["scope_supported"] = (
            None
            if not profile_known or scope is None or excluded is None
            else scope is True and excluded is False and supported_profile
        )
        recipient_current = recipient.compatible(recipient.current(db, cn), trade)
        if not recipient_current:
            data["proof"]["scope_supported"] = False
            data["diagnostics"]["SUPPORTED_SCOPE"] = {
                "recipient_confirmation": "CONFLICT_WITH_ACCEPTED_SNAPSHOT",
                "corrective_action": "Buyer correction or accepted commercial amendment required",
            }
        row.coverage_json = {
            **pack.coverage_json,
            "scope_predicate": scope,
            "scope_profile_supported": supported_profile,
            "independent_verification_dimensions": dimensions,
            "authority_deadlines": data.get("authority_deadlines", []),
        }
        row.limitations_json += pack.limitations_json
        source_state = governance.sources_current(db, pack)
        blocked_source = bool(
            source_state["open_conflicts"] or source_state["non_governing_sources"]
        ) or not all(s["clean"] for s in source_state["sources"])
        bound_sources_current = all(
            d["reference"]["document_version_id"] == d["current_version_id"]
            and d["reference"]["reviewed_fact_revision_id"] == d["effective_fact_revision_id"]
            and d["lifecycle_status"] == "ACTIVE"
            and all(
                a["security_state"] == "CLEAN" and a["hash"] == a["current_hash"]
                for a in d["assets"]
            )
            for d in row.snapshot_json["documents"]
        )
        blocked_source = blocked_source or not bound_sources_current
        rows = []
        for rule in db.scalars(
            select(Rule).where(Rule.pack_revision_id == pack.id).order_by(Rule.rule_code)
        ):
            definition = rule.rule_json
            rule_from = inputs.observations.timestamp(definition["effective_from"])
            rule_until = inputs.observations.timestamp(definition.get("effective_until"))
            basis = at
            if definition["date_basis"] == "INVOICE_DATE":
                from datetime import datetime
                from zoneinfo import ZoneInfo

                day = data["invoice"].get("issue_date")
                basis = (
                    datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                    if day
                    else None
                )
            elif definition["date_basis"] == "PLANNED_ARRIVAL_TIME":
                basis = inputs.observations.timestamp(facts.get("expected_arrival_at"))
            elif definition["date_basis"] == "OBSERVATION_TIME":
                selected_times = [
                    inputs.observations.timestamp(
                        d.get("provider_observed_at") or d.get("checked_at")
                    )
                    for d in dimensions
                    if d.get("selected")
                    and d.get("check_type") == definition.get("observation_check_type")
                ]
                positions = [
                    rule_from <= t and (rule_until is None or t < rule_until)
                    for t in selected_times
                    if t
                ]
                basis = (
                    selected_times[0]
                    if (
                        selected_times
                        and all(selected_times)
                        and (all(positions) or not any(positions))
                    )
                    else None
                )
            applicability = evaluate(definition["applicability_expression"], data)
            if basis is None:
                applicability = None
            elif basis < rule_from or (rule_until and basis >= rule_until):
                applicability = False
            if definition["date_basis"] == "ACTION_TIME":
                for value in (rule_from, rule_until):
                    if value and value > at:
                        deadlines.append(value)
            satisfied = (
                evaluate(definition["satisfaction_expression"], data)
                if applicability is True
                else None
            )
            outcome = (
                "NOT_APPLICABLE"
                if applicability is False
                else "UNKNOWN"
                if applicability is None or satisfied is None
                else "SATISFIED"
                if satisfied is True
                else "FAILED"
            )
            requirement = Requirement(
                evaluation_id=row.id,
                rule_id=rule.id,
                requirement_code=rule.requirement_code,
                rule_class=rule.rule_class,
                applicability="APPLICABLE"
                if applicability is True
                else "NOT_APPLICABLE"
                if applicability is False
                else "UNKNOWN",
                outcome=outcome,
                mandatory=definition["mandatory"],
                severity=definition["severity"],
                expected_json={
                    "required_evidence_types": definition["required_evidence_types"],
                    "date_basis": definition["date_basis"],
                    "date_basis_timestamp": basis.isoformat() if basis else None,
                },
                observed_json={
                    "predicate_result": satisfied,
                    "comparison": data.get("diagnostics", {}).get(
                        definition["requirement_code"], {}
                    ),
                    "correction_links": [
                        {
                            "document_version_id": ref["document_version_id"],
                            "url": f"/documents/versions/{ref['document_version_id']}/review",
                        }
                        for ref in (
                            [
                                data["binding"]["movement_document"],
                                *data["binding"].get("supporting_documents", []),
                            ]
                            if data.get("binding")
                            else []
                        )
                    ],
                },
                evidence_refs_json=public_records.input_references(row.snapshot_json),
                source_ids=definition["source_ids"],
                explanation=definition["explanation_template"],
                remedies_json=definition["remedy_codes"],
                created_by_user_id=ctx.user.id,
            )
            db.add(requirement)
            db.flush()
            rows.append(requirement)
            if outcome in {"FAILED", "UNKNOWN"}:
                db.add(
                    ReviewCase(
                        trade_id=trade.id,
                        consignment_id=cn.id,
                        origin_evaluation_id=row.id,
                        requirement_id=requirement.id,
                        case_type="MANDATORY_BLOCKER"
                        if requirement.mandatory
                        else "POLICY_WARNING",
                        created_by_user_id=ctx.user.id,
                    )
                )
        mandatory_failed = any(r.mandatory and r.outcome in {"FAILED", "UNKNOWN"} for r in rows)
        missing = (
            not profile_known
            or scope is None
            or excluded is None
            or not row.binding_revision_id
            or not row.loading_manifest_revision_id
        )
        operational_block = (
            not recipient.compatible(recipient.current(db, cn), trade)
            or cn.planning_status != "PREPARING"
            or cn.revision_alignment != "CURRENT"
            or cn.movement_status
            != ("NOT_STARTED" if row.action == "PICKUP_CONFIRMED" else "PICKED_UP")
            or any(h["active"] for h in row.snapshot_json["holds"])
            or not (row.snapshot_json.get("current_vehicle") or {}).get("active", False)
            or (row.snapshot_json.get("current_vehicle") or {}).get("vehicle")
            != {
                k: v
                for k, v in (row.snapshot_json.get("assignment") or {})
                .get("vehicle_snapshot", {})
                .items()
                if k != "id"
            }
        )
        binding = db.get(Binding, row.binding_revision_id) if row.binding_revision_id else None
        unsupported_invoice = (
            binding is not None and binding.binding_json.get("whole_invoice_coverage") is not True
        )
        row.decision = (
            "UNSUPPORTED"
            if scope is False
            or excluded is True
            or (profile_known and not supported_profile)
            or unsupported_invoice
            else "BLOCKED"
            if blocked_source or mandatory_failed or missing or operational_block
            else "NEEDS_REVIEW"
            if any(r.outcome in {"FAILED", "UNKNOWN"} for r in rows)
            else "ELIGIBLE_FOR_REVIEW"
        )
        if blocked_source:
            row.limitations_json.append(
                "SOURCE_CONFLICT_UNRESOLVED: source integrity/conflict blocks release."
            )
        if unsupported_invoice:
            row.limitations_json.append(
                "One complete issued invoice per consignment is required; Phase 3 split mapping "
                "is preserved, not proportionally valued for release."
            )
        if missing:
            row.limitations_json.append(
                "Mandatory scope facts, loading manifest or exact bindings are missing/unknown."
            )
        if operational_block:
            row.limitations_json.append(
                "Current movement state, revision alignment or integrity hold blocks this action."
            )
        if not recipient_current:
            row.limitations_json.append(
                "Recipient confirmation conflicts with the accepted snapshot. "
                "Confirm corrected recipient evidence or amend the agreement."
            )
        deadlines += [at + timedelta(seconds=state["default_authorisation_ttl_seconds"])]
        if boundary:
            deadlines.append(boundary)
        deadline = min([deadline, *deadlines])
        row.job_state = "COMPLETED"
    row.valid_until = deadline
    db.add(
        Dependency(
            evaluation_id=row.id,
            dependency_type="EXACT_CONTEXT",
            entity_id=cn.id,
            entity_version=str(row.context_version),
            content_hash=row.dependency_hash,
            observed_at=at,
            freshness_until=deadline,
            dependency_json={"schema": "PH4_DEPENDENCIES_V1"},
            created_by_user_id=ctx.user.id,
        )
    )
    with db.no_autoflush:
        requirement_records = list(
            db.scalars(
                select(Requirement)
                .where(Requirement.evaluation_id == row.id)
                .order_by(Requirement.requirement_code)
            )
        )
    row.evaluation_hash = digest(
        {
            "id": row.id,
            "action": row.action,
            "dependency": row.dependency_hash,
            "decision": row.decision,
            "coverage": row.coverage_json,
            "valid_until": deadline.isoformat(),
            "requirements": [view(r) for r in requirement_records],
        }
    )
    record(
        db,
        ctx,
        "COMPLIANCE_EVALUATION_COMPLETED",
        row,
        summary={"decision": row.decision, "evaluation_hash": row.evaluation_hash},
    )
    return row


def read(db, ctx, ident):
    row, trade, cn, side = exact(db, ctx, ident)
    requirements = [
        public_records.requirement(db, ctx, r)
        for r in db.scalars(
            select(Requirement)
            .where(Requirement.evaluation_id == row.id)
            .order_by(Requirement.requirement_code)
        )
    ]
    from .packet_options import sources as packet_sources
    from .review_authority import release_preparers

    reasons = []
    if ctx.user.id in release_preparers(db, row):
        reasons.append("SELF_REVIEW_NOT_ALLOWED")
    freshness = current(db, row, trade, cn)
    if freshness != "CURRENT":
        reasons.append("EVALUATION_STALE")
    if row.decision not in {"ELIGIBLE_FOR_REVIEW", "NEEDS_REVIEW"}:
        reasons.append("COMPLIANCE_NOT_READY")
    return {
        "id": row.id,
        "warning_acknowledgment_options": [
            {"id": a.id, "requirement_id": a.requirement_id, "reason": a.reason}
            for a in db.scalars(
                select(CaseAction)
                .where(
                    CaseAction.evaluation_id == row.id,
                    CaseAction.action == "ACKNOWLEDGE_POLICY_WARNING",
                )
                .order_by(CaseAction.created_at, CaseAction.id)
            )
        ],
        "release_review_blockers": reasons,
        "packet_source_options": packet_sources(db, ctx, row, trade),
        "release_reviews": [
            {
                "id": r.id,
                "decision": r.decision,
                "reviewer_user_id": r.created_by_user_id,
                "valid_until": aware(r.valid_until).isoformat(),
            }
            for r in db.scalars(
                select(ReleaseReview)
                .where(ReleaseReview.evaluation_id == row.id)
                .order_by(ReleaseReview.created_at.desc(), ReleaseReview.id.desc())
            )
        ],
        "packets": [
            {
                "id": p.id,
                "packet_hash": p.packet_hash,
                "assignment_id": p.assignment_id,
                "carry_methods": sorted({i["carry_method"] for i in p.manifest_json["items"]}),
                "acknowledgments": [
                    {"id": a.id, "driver_user_id": a.created_by_user_id}
                    for a in db.scalars(
                        select(PacketAck)
                        .where(PacketAck.packet_id == p.id)
                        .order_by(PacketAck.created_at.desc(), PacketAck.id.desc())
                    )
                ],
            }
            for p in db.scalars(
                select(Packet)
                .where(Packet.evaluation_id == row.id)
                .order_by(Packet.created_at.desc(), Packet.id.desc())
            )
        ],
        "action": row.action,
        "execution_mode": row.execution_mode,
        "job_state": row.job_state,
        "decision": row.decision,
        "freshness": freshness,
        "context_version": row.context_version,
        "evaluation_hash": row.evaluation_hash,
        "evaluated_at": aware(row.evaluated_at).isoformat() if row.evaluated_at else None,
        "valid_until": aware(row.valid_until).isoformat() if row.valid_until else None,
        "coverage": row.coverage_json,
        "independent_verification_dimensions": row.coverage_json.get(
            "independent_verification_dimensions", []
        ),
        "requirements": requirements,
        "blockers": [
            r["id"]
            for r in requirements
            if r["mandatory"] and r["outcome"] in {"FAILED", "UNKNOWN"}
        ],
        "warnings": [
            r["id"]
            for r in requirements
            if not r["mandatory"] and r["outcome"] in {"FAILED", "UNKNOWN"}
        ],
        "limitations": row.limitations_json,
        "permitted_next_actions": ["CORRECT_EVIDENCE", "REEVALUATE"]
        if row.decision != "ELIGIBLE_FOR_REVIEW"
        else ["INDEPENDENT_RELEASE_REVIEW"],
    }


def history(db, ctx, ident, cursor=None):
    context.access(db, ctx, ident)
    query = select(Evaluation).where(Evaluation.consignment_id == ident)
    if cursor:
        from sqlalchemy import and_, or_

        previous = exists(db, Evaluation, cursor)
        if previous.consignment_id != ident:
            fail("NOT_FOUND", "Evaluation cursor not found.", status=404)
        query = query.where(
            or_(
                Evaluation.created_at < previous.created_at,
                and_(Evaluation.created_at == previous.created_at, Evaluation.id < previous.id),
            )
        )
    rows = db.scalars(
        query.order_by(Evaluation.created_at.desc(), Evaluation.id.desc()).limit(51)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "action": row.action,
                "job_state": row.job_state,
                "decision": row.decision,
                "evaluation_hash": row.evaluation_hash,
                "evaluated_at": aware(row.evaluated_at).isoformat() if row.evaluated_at else None,
                "context_version": row.context_version,
            }
            for row in rows[:50]
        ],
        "next_cursor": rows[49].id if len(rows) > 50 else None,
    }
