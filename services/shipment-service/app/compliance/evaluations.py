"""Durable asynchronous deterministic evaluations and live dependency currency."""

from sqlalchemy import select

from app.document_desk.models import Job, Outbox
from app.operations.access import exists, fail
from app.trades.terms import digest

from . import calculation, context, governance, incremental, preparation, public_records
from .clock import aware, instant
from .expression import ENGINE_VERSION
from .ledger import check_context, record, view
from .models import (
    CaseAction,
    Dependency,
    Evaluation,
    Packet,
    PacketAck,
    ReleaseReview,
    Requirement,
    ReviewCase,
)


def request(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "compliance.evaluate", True, True)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    at = instant(db)
    _, registry, _ = governance.resolve(db, trade.execution_mode, at)
    snapshot, fingerprint = context.dependency_snapshot(db, trade, cn, registry, assessment_time=at)
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
    _, fingerprint = context.dependency_snapshot(db, trade, cn, registry, assessment_time=at)
    if row.dependency_hash != fingerprint or row.execution_mode != trade.execution_mode:
        return "STALE"
    if row.valid_until is not None and at >= aware(row.valid_until):
        return "EXPIRED"
    return "CURRENT"


def exact(db, ctx, ident, permission="compliance.read", seller=False):
    row = exists(db, Evaluation, ident)
    trade, cn, side = context.access(db, ctx, row.consignment_id, permission, seller, True)
    return row, trade, cn, side


def persist_evaluation(db, ctx, row, result, at, execution=None):
    row.evaluated_at, row.valid_until = at, calculation.timestamp(result["valid_until"])
    row.decision = result["decision"]
    row.coverage_json, row.limitations_json = result["coverage"], result["limitations"]
    for value in result["requirements"]:
        requirement = Requirement(evaluation_id=row.id, created_by_user_id=ctx.user.id, **value)
        db.add(requirement)
        db.flush()
        if requirement.outcome in {"FAILED", "UNKNOWN"}:
            db.add(
                ReviewCase(
                    trade_id=row.trade_id,
                    consignment_id=row.consignment_id,
                    origin_evaluation_id=row.id,
                    requirement_id=requirement.id,
                    case_type="MANDATORY_BLOCKER" if requirement.mandatory else "POLICY_WARNING",
                    created_by_user_id=ctx.user.id,
                )
            )
    db.add(
        Dependency(
            evaluation_id=row.id,
            dependency_type="EXACT_CONTEXT",
            entity_id=row.consignment_id,
            entity_version=str(row.context_version),
            content_hash=row.dependency_hash,
            observed_at=at,
            freshness_until=row.valid_until,
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
            "valid_until": row.valid_until.isoformat(),
            "requirements": [view(r) for r in requirement_records],
        }
    )
    if execution is not None:
        incremental.retain(db, ctx, row, execution, at)
    row.job_state = result["job_state"]
    record(
        db,
        ctx,
        "COMPLIANCE_EVALUATION_COMPLETED",
        row,
        summary={"decision": row.decision, "evaluation_hash": row.evaluation_hash},
    )
    return row


def complete(db, ctx, ident):
    row, trade, cn, _ = exact(db, ctx, ident, "compliance.evaluate", True)
    if row.job_state not in {"QUEUED", "RUNNING"}:
        fail("JOB_ALREADY_TERMINAL", "Evaluation already completed.")
    at = instant(db)
    snapshot, rules = preparation.prepare_snapshot(db, trade, cn, row, at)
    result, execution = incremental.execute(db, ctx, row, snapshot, rules, at)
    return persist_evaluation(db, ctx, row, result, at, execution)


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
