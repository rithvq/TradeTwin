"""Live organization-scoped dashboard. Existing readiness remains the only movement gate."""

from datetime import timedelta

from sqlalchemy import or_, select

from app.operations.access import has
from app.operations.models import Assignment, Consignment
from app.trades.errors import TradeError
from app.trades.models import Participant

from . import (
    authorization_window,
    computation_trace,
    context,
    dashboard_binding,
    evaluations,
    evidence_changes,
    handoff,
)
from . import dashboard_stages as stages
from .calculation import timestamp
from .clock import aware, instant
from .models import Authorization, Evaluation

EXPIRING_SECONDS = 300


def links(db, ctx, cn, action, side):
    output = []
    if not has(db, ctx, "consignment.read", cn.trade_id, side):
        return output
    if side:
        output.append(
            {
                "label": "Open compliance desk",
                "href": f"/shipments/trades/{cn.trade_id}/operations?module=Compliance"
                f"&consignment={cn.id}&dispatch_action={action}#dispatch-{cn.id}",
            }
        )
    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    if assignment and not side:
        output.append(
            {"label": "Open dispatch desk", "href": f"/shipments/consignments/{cn.id}/assignment"}
        )
    if (
        assignment
        and assignment.driver_user_id == ctx.user.id
        and has(db, ctx, "shipment.event.record", cn.trade_id)
    ):
        output.append(
            {"label": "Open assigned driver task", "href": f"/shipments/tasks/{assignment.id}"}
        )
    return output


def reasons(readiness):
    requirements = {
        r["id"]: r["requirement_code"] + ":" + r["outcome"]
        for r in (readiness.get("evaluation") or {}).get("requirements", [])
    }
    return sorted({requirements.get(code, code) for code in readiness["reasons"]})


def row_state(cn, readiness):
    if cn.movement_status not in {"NOT_STARTED", "PICKED_UP"}:
        return "MOVED"
    if readiness["state"] == "READY":
        return "READY"
    if readiness.get("authorisation") and readiness["authorisation"]["effective_state"] != "ACTIVE":
        return "BLOCKED"
    if readiness["state"] in {"NOT_ASSESSED", "EVALUATING", "ELIGIBLE_FOR_REVIEW", "NEEDS_REVIEW"}:
        return "AWAITING_EVIDENCE_OR_REVIEW"
    return "BLOCKED"


def current_stage(gate):
    if not gate:
        return "MOVEMENT_RECORDED"
    if gate["state"] == "READY":
        return "READY_TO_MOVE"
    if not gate["evaluation"]:
        return "EVIDENCE"
    if gate["evaluation"]["job_state"] in {"QUEUED", "RUNNING"}:
        return "RULE_CALCULATION"
    if gate["authorisation"]:
        return "AUTHORIZATION"
    return "RELEASE_REVIEW"


def listing(db, ctx, cursor=None, limit=20):
    # SQL bounds candidate access to this organization; exact live permissions are
    # still checked below, including trade-scoped grants and the assigned driver.
    participant = (
        select(Participant.id)
        .where(
            Participant.trade_id == Consignment.trade_id, Participant.organization_id == ctx.org_id
        )
        .exists()
    )
    assigned = (
        select(Assignment.id)
        .where(
            Assignment.consignment_id == Consignment.id,
            Assignment.carrier_organization_id == ctx.org_id,
            Assignment.status.in_(["PROPOSED", "ACCEPTED"]),
        )
        .exists()
    )
    query = (
        select(Consignment)
        .where(or_(participant, assigned))
        .order_by(Consignment.created_at.desc(), Consignment.id.desc())
    )
    if cursor:
        context.access(db, ctx, cursor)
    checked_at = instant(db)
    counts = {
        "ready_to_move": 0,
        "awaiting_evidence_or_review": 0,
        "expiring_soon": 0,
        "blocked": 0,
    }
    rows, seen_cursor, total = [], cursor is None, 0
    for cn in list(db.scalars(query)):
        # Release per-consignment read locks before visiting another trade. Rolling
        # back this read-only savepoint retains no business writes and releases PG locks.
        savepoint = db.begin_nested()
        try:
            trade, cn, side = context.access(db, ctx, cn.id, lock=True)
            action = "DEPARTED" if cn.movement_status != "NOT_STARTED" else "PICKUP_CONFIRMED"
            gate = (
                handoff.readiness(db, ctx, cn.id, action)
                if cn.movement_status in {"NOT_STARTED", "PICKED_UP"}
                else None
            )
            state = row_state(cn, gate) if gate else "MOVED"
            authorization = (gate or {}).get("authorisation")
            expires = authorization.get("expires_at") if authorization else None
            expiring = False
            if expires and state == "READY":
                expiring = (
                    checked_at
                    < timestamp(expires)
                    <= checked_at + timedelta(seconds=EXPIRING_SECONDS)
                )
            key = {
                "READY": "ready_to_move",
                "AWAITING_EVIDENCE_OR_REVIEW": "awaiting_evidence_or_review",
                "BLOCKED": "blocked",
            }.get(state)
            if key:
                counts[key] += 1
            counts["expiring_soon"] += int(expiring)
            total += 1
            if seen_cursor and len(rows) < limit + 1:
                rows.append(
                    {
                        "consignment_id": cn.id,
                        "reference": cn.reference,
                        "trade_id": trade.id,
                        "trade_reference": trade.reference,
                        "execution_mode": trade.execution_mode,
                        "movement_status": cn.movement_status,
                        "action": action,
                        "state": state,
                        "readiness_state": gate["state"] if gate else "HISTORICAL_MOVEMENT",
                        "current_stage": current_stage(gate),
                        "reason_codes": reasons(gate) if gate else [],
                        "expiring_soon": expiring,
                        "expires_at": expires,
                        "checked_at": gate["checked_at"] if gate else checked_at.isoformat(),
                        "links": links(db, ctx, cn, action, side),
                    }
                )
            if cn.id == cursor:
                seen_cursor = True
        except TradeError as error:
            if error.status not in {403, 404}:
                raise
        finally:
            savepoint.rollback()
    return {
        "schema_version": "DISPATCH_DASHBOARD_V1",
        "checked_at": checked_at.isoformat(),
        "organization_id": ctx.org_id,
        "counts": counts,
        "counts_scope": "ALL_AUTHORIZED_CONSIGNMENTS",
        "expiring_within_seconds": EXPIRING_SECONDS,
        "total": total,
        "items": rows[:limit],
        "next_cursor": rows[limit - 1]["consignment_id"] if len(rows) > limit else None,
    }


def authorization_stage(authorization, checked_at):
    if not authorization:
        return stages.stage(5, "Authorization", "NOT_ISSUED")
    code = authorization["effective_state"]
    status = {
        "ACTIVE": "ACTIVE",
        "AUTHORISATION_CONSUMED": "CONSUMED",
        "AUTHORISATION_REVOKED": "REVOKED",
        "AUTHORISATION_EXPIRED": "EXPIRED",
    }.get(code, "UNUSABLE")
    if status == "EXPIRED" and timestamp(authorization["valid_from"]) > timestamp(checked_at):
        status = "NOT_YET_VALID"
    return stages.stage(
        5,
        "Authorization",
        status,
        {
            "authorization_id": authorization["id"],
            "evaluation_id": authorization["evaluation_id"],
            "issued_at": authorization["issued_at"],
            "valid_from": authorization["valid_from"],
            "expires_at": authorization["expires_at"],
        },
        [code] if status == "UNUSABLE" else [],
    )


def journey(db, ctx, ident, action):
    savepoint = db.begin_nested()
    try:
        trade, cn, side = context.access(db, ctx, ident, lock=True)
        gate = handoff.readiness(db, ctx, cn.id, action)
        event, consumed, movement_stages = stages.movement(db, cn, action)
        authorization = (
            stages.dispatch.read(db, ctx, consumed.id) if consumed else gate["authorisation"]
        )
        evaluation = gate["evaluation"]
        if consumed and (not evaluation or evaluation["id"] != consumed.evaluation_id):
            evaluation = evaluations.read(db, ctx, authorization["evaluation_id"])
        row = db.get(Evaluation, evaluation["id"]) if evaluation else None
        snapshot = stages.stage(
            2,
            "Snapshot",
            evaluation["freshness"] if evaluation else "NOT_CAPTURED",
            {
                "captured_at": aware(row.created_at).isoformat() if row else None,
                "fingerprint_short": row.dependency_hash[:12] if row else None,
                "fingerprint_algorithm": "SHA-256",
                "historical": bool(event),
            },
        )
        return {
            "schema_version": "DISPATCH_JOURNEY_V1",
            "consignment_id": cn.id,
            "reference": cn.reference,
            "trade_id": trade.id,
            "action": action,
            "execution_mode": trade.execution_mode,
            "checked_at": gate["checked_at"],
            "readiness_state": gate["state"],
            "historical": bool(event),
            "evidence_changes": evidence_changes.read(
                db, ctx, row, trade, cn, evaluation["freshness"], timestamp(gate["checked_at"])
            )
            if row
            else {
                "status": "NOT_ASSESSED",
                "detail_status": "NOT_RECORDED",
                "reason_codes": [],
                "transitions": [],
                "notice": "Detail not recorded.",
            },
            "calculation": computation_trace.read(db, ctx, row.id) if row else None,
            "binding": dashboard_binding.read(
                db, row, trade, cn, authorization, bool(event), (evaluation or {}).get("freshness")
            ),
            "validity": authorization_window.read(db, db.get(Authorization, authorization["id"]))
            if authorization
            else {"detail_status": "NOT_RECORDED", "notice": "Detail not recorded."},
            "post_dispatch_alerts": [
                {"code": a["code"], "severity": a["severity"]}
                for a in gate.get("operational_alerts", [])
            ],
            "links": links(db, ctx, cn, action, side),
            "stages": [
                stages.evidence(db, cn, evaluation, bool(event)),
                snapshot,
                stages.compliance(db, evaluation),
                stages.release(db, trade, cn, evaluation, authorization, bool(event)),
                authorization_stage(authorization, gate["checked_at"]),
                *movement_stages,
            ],
        }
    finally:
        savepoint.rollback()
