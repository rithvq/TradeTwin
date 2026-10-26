"""Small recipient-safe projections; source contents and full hashes stay in existing desks."""

from sqlalchemy import select

from app.operations.models import Assignment, Event, Vehicle
from app.trades.errors import TradeError
from app.trades.models import Audit

from . import context, dispatch
from .clock import aware
from .models import Authorization, Evaluation, Packet, ReleaseReview
from .models_computation import EvaluationExecution


def stage(number, name, status, facts=None, reasons=None, items=None):
    return {
        "number": number,
        "name": name,
        "status": status,
        "facts": facts or {},
        "reason_codes": sorted(set(reasons or [])),
        "items": items or [],
    }


def evidence(db, cn, evaluation, historical):
    head = context.heads(db, cn)
    requirements = {r["requirement_code"]: r for r in (evaluation or {}).get("requirements", [])}
    current = historical or (evaluation or {}).get("freshness") == "CURRENT"
    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    vehicle = db.get(Vehicle, assignment.vehicle_id) if assignment else None
    groups = [
        (
            "Documents",
            bool(head and head.current_binding_revision_id),
            ["MOVEMENT_INVOICE", "INVOICE_FORMALITIES", "EINVOICE_REQUIRED", "EWB_REQUIRED"],
        ),
        (
            "Verification",
            bool(head and head.current_binding_revision_id),
            ["AUTHORITY_ASSURANCE", "EINVOICE_PROOF", "EWB_VALIDITY", "TRANSPORT_ASSURANCE"],
        ),
        (
            "Quantities",
            bool(head and head.current_loading_manifest_revision_id),
            ["LOADING_MANIFEST"],
        ),
        (
            "Manifest",
            bool(head and head.current_loading_manifest_revision_id),
            ["LOADING_MANIFEST"],
        ),
        ("Assignment", bool(assignment), ["TRANSPORT_ASSURANCE"]),
        ("Corridor", bool(head and head.current_fact_revision_id), ["SUPPORTED_SCOPE"]),
    ]
    items = []
    for label, present, codes in groups:
        observed = [requirements[c] for c in codes if c in requirements]
        bad = [
            r["requirement_code"] + ":" + r["outcome"]
            for r in observed
            if r["outcome"] not in {"SATISFIED", "NOT_APPLICABLE"}
        ]
        if (
            label == "Assignment"
            and not historical
            and (
                not assignment
                or assignment.status != "ACCEPTED"
                or not vehicle
                or not vehicle.active
            )
        ):
            bad.append("ASSIGNMENT_NOT_CURRENT")
        status = (
            "MISSING"
            if not present
            else "COMPLETE"
            if current and observed and not bad
            else "NEEDS_ATTENTION"
        )
        items.append({"label": label, "status": status, "reason_codes": bad})
    overall = (
        "MISSING"
        if any(i["status"] == "MISSING" for i in items)
        else ("COMPLETE" if all(i["status"] == "COMPLETE" for i in items) else "NEEDS_ATTENTION")
    )
    return stage(1, "Evidence", overall, items=items)


def release(db, trade, cn, evaluation, authorization, historical):
    if not evaluation:
        return stage(
            4,
            "Release",
            "PENDING",
            items=[
                {"label": label, "status": "PENDING", "reason_codes": []}
                for label in ("Independent review", "Dispatch packet", "Driver acknowledgment")
            ],
        )
    review = (
        db.get(ReleaseReview, authorization["approval_id"])
        if authorization
        else db.scalar(
            select(ReleaseReview)
            .where(ReleaseReview.evaluation_id == evaluation["id"])
            .order_by(ReleaseReview.created_at.desc(), ReleaseReview.id.desc())
            .limit(1)
        )
    )
    packet = (
        db.get(Packet, authorization["packet_id"])
        if authorization
        else db.scalar(
            select(Packet)
            .where(Packet.evaluation_id == evaluation["id"])
            .order_by(Packet.created_at.desc(), Packet.id.desc())
            .limit(1)
        )
    )
    reviewed, packed, acked = "PENDING", "PENDING", "PENDING"
    reasons = []
    if review:
        try:
            if not historical:
                dispatch.approval(db, db.get(Evaluation, evaluation["id"]), review.id)
            reviewed = "COMPLETE" if review.decision == "APPROVE_RELEASE" else "REJECTED"
        except TradeError as error:
            reviewed = "NEEDS_ATTENTION"
            reasons.append(error.code)
    if packet:
        try:
            if not historical:
                dispatch.packet_current(db, packet, trade, cn)
            packed = "COMPLETE"
        except TradeError as error:
            packed = "NEEDS_ATTENTION"
            reasons.append(error.code)
        acknowledgments = next(
            (p["acknowledgments"] for p in evaluation["packets"] if p["id"] == packet.id), []
        )
        current_assignment = db.get(Assignment, packet.assignment_id)
        if any(a["driver_user_id"] == current_assignment.driver_user_id for a in acknowledgments):
            acked = "COMPLETE" if packed == "COMPLETE" else "NEEDS_ATTENTION"
    items = [
        {"label": label, "status": status, "reason_codes": []}
        for label, status in zip(
            ("Independent review", "Dispatch packet", "Driver acknowledgment"),
            (reviewed, packed, acked),
            strict=True,
        )
    ]
    return stage(
        4,
        "Release",
        "COMPLETE" if all(i["status"] == "COMPLETE" for i in items) else "PENDING",
        reasons=reasons,
        items=items,
    )


def movement(db, cn, action):
    event = db.scalar(
        select(Event)
        .where(Event.consignment_id == cn.id, Event.event_type == action)
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(1)
    )
    rejected = db.scalar(
        select(Audit)
        .where(
            Audit.consignment_id == cn.id,
            Audit.action == "DISPATCH_MOVEMENT_REJECTED",
            Audit.redacted_summary_json["action"].as_string() == action,
        )
        .order_by(Audit.created_at.desc(), Audit.id.desc())
        .limit(1)
    )
    if event:
        authorization = db.scalar(
            select(Authorization).where(Authorization.consumed_event_id == event.id)
        )
        facts = {
            "movement_event_id": event.id,
            "recorded_at": aware(event.created_at).isoformat(),
            "occurred_at": aware(event.occurred_at).isoformat(),
            "consumed_authorization_id": authorization.id if authorization else None,
        }
        if rejected and aware(rejected.created_at) > aware(event.created_at):
            facts["subsequent_rejection_code"] = rejected.redacted_summary_json["reason_code"]
        return (
            event,
            authorization,
            [
                stage(
                    6,
                    "Movement check",
                    "PASSED" if authorization else "NOT_RECORDED",
                    {"checked_at": facts["recorded_at"]},
                    [] if authorization else ["HISTORICAL_AUTHORIZATION_NOT_RECORDED"],
                ),
                stage(7, "Result", "RECORDED", facts),
            ],
        )
    if rejected:
        reasons = [rejected.redacted_summary_json["reason_code"]]
        facts = {"attempted_at": aware(rejected.created_at).isoformat()}
        return (
            None,
            None,
            [
                stage(6, "Movement check", "REJECTED", facts, reasons),
                stage(7, "Result", "REJECTED", facts, reasons),
            ],
        )
    return None, None, [stage(6, "Movement check", "PENDING"), stage(7, "Result", "PENDING")]


def compliance(db, evaluation):
    if not evaluation:
        return stage(3, "Compliance", "NOT_ASSESSED")
    execution = db.scalar(
        select(EvaluationExecution).where(EvaluationExecution.evaluation_id == evaluation["id"])
    )
    trace = execution.trace_json if execution else {}
    actual_incremental = trace.get("authoritative_strategy") == "INCREMENTAL"
    facts = {
        "evaluation_id": evaluation["id"],
        "decision": evaluation["decision"],
        "evaluated_at": evaluation["evaluated_at"],
        "strategy": trace.get("authoritative_strategy", "FULL"),
        "rules_recomputed": trace.get("rules_recomputed"),
        "rules_reused": trace.get("rules_reused", 0) if actual_incremental else 0,
    }
    blockers = [
        {
            "label": r["requirement_code"],
            "status": r["outcome"],
            "reason_codes": [r["requirement_code"] + ":" + r["outcome"]],
            "description": r["explanation"],
        }
        for r in evaluation["requirements"]
        if r["outcome"] in {"FAILED", "UNKNOWN"}
    ]
    return stage(
        3, "Compliance", evaluation["decision"] or evaluation["job_state"], facts, items=blockers
    )
