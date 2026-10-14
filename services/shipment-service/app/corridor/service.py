"""Application commands and price-free operational projections."""

from datetime import timedelta

from sqlalchemy import select

from app.compliance import context
from app.compliance.clock import aware, instant
from app.compliance.ledger import record, view
from app.freight.access import planning
from app.operations.access import consignment, exists, fail, has, match
from app.operations.ledger import touch
from app.operations.models import Assignment
from app.trades.terms import digest

from . import impact, projection
from .models import Assessment, Coverage, DriverResponse, ImpactItem, MotionHead, RecoveryCase


def guard(db, trade, cn):
    dependency = projection.dependency(db, trade, cn)
    if dependency and dependency["outcome"] in {"BLOCKED", "NEEDS_REVIEW"}:
        fail(
            "CORRIDOR_MOVEMENT_ACTION_BLOCKED",
            "Current corridor evidence blocks this action. Reassess and obtain a fresh release; "
            "operational protection does not mean the vehicle has physically stopped.",
            details={
                "outcome": dependency["outcome"],
                "permitted_next_actions": ["REASSESS_CORRIDOR", "RECORD_DRIVER_OBSERVATION"],
            },
        )


def dynamic_context(db, ctx, ident):
    trade, cn, _ = consignment(db, ctx, ident)
    current = projection.plan(db, cn)
    captured = projection.capture(db, trade, cn)
    result = impact.evaluate_plan(db, current, captured) if current else None
    cases = list(
        db.scalars(
            select(RecoveryCase)
            .where(RecoveryCase.consignment_id == cn.id)
            .order_by(RecoveryCase.created_at.desc())
        )
    )
    capabilities = [
        p
        for p in [
            "tradetwin.run",
            "tradetwin.plan.apply",
            "shipment.event.record",
            "regulation.source.register",
        ]
        if has(db, ctx, p, trade.id)
    ]
    # Private source titles/provenance never leak through a shared operational response.
    public_events = [e for e in captured["events"] if event_visible(db, ctx, e)]
    if result:
        allowed = {e["id"] for e in public_events}
        result["items"] = [
            i
            if i["event_revision_id"] in allowed
            else {
                "outcome": i["outcome"],
                "effect": i["effect"],
                "section_index": i["section_index"],
                "edge_key": i["edge_key"],
                "limitations": [
                    "Restricted source evidence; request review from its authorised owner."
                ],
            }
            for i in result["items"]
        ]
    version = context.version(db, trade.id)
    return {
        "consignment_id": cn.id,
        "reference": cn.reference,
        "execution_mode": trade.execution_mode,
        "movement_status": cn.movement_status,
        "context_version": version,
        "etag": f'"{version}"',
        "dynamic_context_hash": captured["projection_hash"],
        "current_route_plan_revision_id": current.id if current else None,
        "scope_epochs": captured["scope_epochs"],
        "coverage": captured["coverage"],
        "impact": result,
        "events": [
            {
                k: e[k]
                for k in (
                    "id",
                    "incident_id",
                    "headline",
                    "severity",
                    "state",
                    "source_reference",
                    "source_issued_at",
                    "limitations",
                )
            }
            for e in public_events
        ],
        "recovery_cases": [case_view(db, ctx, r) for r in cases],
        "capabilities": capabilities,
    }


def event_visible(db, ctx, event):
    from .models import Incident

    incident = db.get(Incident, event["incident_id"])
    return incident.visibility == "PUBLIC_APPROVED" or incident.owner_organisation_id == ctx.org_id


def reassess(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.run", True)
    if ctx.if_match != f'"{context.version(db, trade.id)}"':
        fail("RUN_STALE", "Reload the compliance context ETag.", status=412)
    current = projection.plan(db, cn)
    captured = projection.capture(db, trade, cn)
    if (
        not current
        or current.id != str(payload.current_route_plan_revision_id)
        or captured["projection_hash"] != payload.expected_context_hash
    ):
        fail("RUN_STALE", "Current route or corridor inputs changed.", status=412)
    at = instant(db)
    result = impact.evaluate_plan(db, current, captured)
    coverage = Coverage(
        consignment_id=cn.id,
        execution_mode=trade.execution_mode,
        coverage_json={**captured["coverage"], "as_of": at.isoformat()},
        content_hash=digest(captured["coverage"]),
        created_by_user_id=ctx.user.id,
    )
    db.add(coverage)
    db.flush()
    row = Assessment(
        trade_id=trade.id,
        consignment_id=cn.id,
        route_plan_revision_id=current.id,
        coverage_snapshot_id=coverage.id,
        execution_mode=trade.execution_mode,
        evaluated_as_of=at,
        valid_until=min(at + timedelta(seconds=300), aware_from(captured["valid_until"]))
        if captured["valid_until"]
        else at + timedelta(seconds=300),
        input_json=captured,
        result_json=result,
        content_hash=digest({"input": captured, "result": result}),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    for item in result["items"]:
        db.add(
            ImpactItem(
                assessment_id=row.id,
                event_revision_id=item["event_revision_id"],
                policy_revision_id=item["policy_revision_id"],
                impact_json=item,
            )
        )
    record(db, ctx, "CORRIDOR_ASSESSMENT_RETAINED", row)
    return assessment_view(db, ctx, row)


def aware_from(value):
    from datetime import datetime

    return aware(datetime.fromisoformat(value))


def assessment_view(db, ctx, row):
    trade, cn, _ = consignment(db, ctx, row.consignment_id)
    captured = projection.capture(db, trade, cn)
    body = {
        "id": row.id,
        "content_hash": row.content_hash,
        "evaluated_as_of": aware(row.evaluated_as_of).isoformat(),
        "valid_until": aware(row.valid_until).isoformat(),
        "freshness": "CURRENT"
        if captured["projection_hash"] == row.input_json["projection_hash"]
        and instant(db) < aware(row.valid_until)
        else "STALE",
        "route_plan_revision_id": row.route_plan_revision_id,
        "result": dict(row.result_json),
    }
    allowed = {e["id"] for e in row.input_json["events"] if event_visible(db, ctx, e)}
    body["result"]["items"] = [
        i
        if i["event_revision_id"] in allowed
        else {
            "outcome": i["outcome"],
            "edge_key": i["edge_key"],
            "limitations": ["Restricted source evidence."],
        }
        for i in body["result"]["items"]
    ]
    return body


def create_case(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.plan.apply", True)
    match(ctx, cn)
    assessment = exists(db, Assessment, payload.assessment_id)
    if assessment.consignment_id != cn.id or assessment.route_plan_revision_id != str(
        payload.current_route_plan_revision_id
    ):
        fail("NOT_FOUND", "Assessment not found in this consignment.", status=404)
    if assessment_view(db, ctx, assessment)["freshness"] != "CURRENT":
        fail("RECOVERY_CONTEXT_STALE", "A fresh current-route assessment is required.", status=412)
    current = db.scalar(
        select(RecoveryCase).where(
            RecoveryCase.consignment_id == cn.id,
            RecoveryCase.status.not_in(["RESOLVED", "CLOSED_NO_CHANGE", "ESCALATED_UNSUPPORTED"]),
        )
    )
    if current:
        return case_view(db, ctx, current)
    if cn.movement_status in {"ARRIVED", "DELIVERY_CLOSED"}:
        status, protection = "ESCALATED_UNSUPPORTED", "MONITOR_ONLY"
    else:
        status = "DETECTED"
        protection = (
            "PREPARATION_BLOCKED"
            if cn.movement_status == "NOT_STARTED"
            else "MOVEMENT_ACTION_BLOCKED"
        )
    row = RecoveryCase(
        trade_id=trade.id,
        consignment_id=cn.id,
        assessment_id=assessment.id,
        status=status,
        protection_state=protection,
        case_json={
            "reason": payload.reason,
            "route_plan_revision_id": str(payload.current_route_plan_revision_id),
            "stage_at_detection": cn.movement_status,
            "assignment_id": cn.active_assignment_id,
            "movement_not_physically_stopped": True,
            "execution_support": "ASSESSMENT_AND_DRIVER_RESPONSE_ONLY",
            "limitation": (
                "Atomic carrier amendments, approved anchors and RECOVERY_RESUME "
                "are not enabled by this incremental migration."
            ),
        },
        created_by=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "CORRIDOR_RECOVERY_DETECTED", row)
    return case_view(db, ctx, row)


def case_view(db, ctx, row):
    _, cn, _ = consignment(db, ctx, row.consignment_id)
    motion = db.get(MotionHead, cn.id)
    return {
        **view(row),
        "etag": f'"{row.row_version}"',
        "motion": motion.motion if motion else "UNKNOWN",
        "stationary_epoch": motion.stationary_epoch if motion else 0,
        "driver_response_allowed": has(db, ctx, "shipment.event.record", row.trade_id),
        "anchor_approved": False,
        "resume_authorised": False,
    }


def driver_response(db, ctx, ident, payload):
    row = exists(db, RecoveryCase, ident)
    trade, cn, _ = consignment(db, ctx, row.consignment_id, "shipment.event.record", lock=True)
    match(ctx, row)
    if not cn.active_assignment_id:
        fail("ASSIGNMENT_CHANGED", "Driver reporting requires a current accepted assignment.")
    assignment = exists(db, Assignment, cn.active_assignment_id)
    if assignment.driver_user_id != ctx.user.id or assignment.status != "ACCEPTED":
        fail("FORBIDDEN", "Only the current assigned driver may report motion.", status=403)
    at = instant(db)
    if payload.observed_at > at:
        fail("VALIDATION_ERROR", "Observed time cannot be in the future.", status=422)
    data = payload.model_dump(mode="json")
    response = DriverResponse(
        recovery_case_id=row.id,
        assignment_id=assignment.id,
        action=payload.action,
        observed_at=payload.observed_at,
        response_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(response)
    db.flush()
    motion = db.get(MotionHead, cn.id)
    if not motion:
        motion = MotionHead(consignment_id=cn.id, stationary_epoch=0, motion="UNKNOWN")
        db.add(motion)
    previous = (
        db.get(DriverResponse, motion.latest_response_id) if motion.latest_response_id else None
    )
    if not previous or payload.observed_at >= aware(previous.observed_at):
        if payload.action in {"REPORT_MOVING", "CONFIRM_REPORTED_STOPPED", "CANNOT_STOP_SAFELY"}:
            motion.stationary_epoch += 1
            motion.motion = (
                "REPORTED_STOPPED"
                if payload.action == "CONFIRM_REPORTED_STOPPED"
                else "REPORTED_MOVING"
                if payload.action == "REPORT_MOVING"
                else "UNKNOWN"
            )
            motion.latest_response_id = response.id
    touch(row)
    record(db, ctx, "CORRIDOR_DRIVER_RESPONSE_RECORDED", response)
    return {
        "id": response.id,
        "case": case_view(db, ctx, row),
        "stop_verified": False,
        "financial_approval": False,
    }
