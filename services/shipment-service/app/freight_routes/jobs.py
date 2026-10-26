"""Leased comparisons fetch outside DB locks and revalidate authority/context before publication."""

from copy import deepcopy
from datetime import timedelta

from sqlalchemy import select

from app.compliance.clock import aware, instant
from app.document_desk import jobs as queue
from app.document_desk.models import Job, Outbox
from app.freight.access import planning, price_access
from app.operations.access import exists, fail
from app.operations.ledger import record
from app.trades.errors import TradeError
from app.trades.terms import digest

from .context import capture
from .engine import evaluate
from .models import RouteStudy
from .ranking import ENGINE_VERSION
from .schemas import StudyInput

STAGE = "FREIGHT_ROUTE_STUDY"


def request(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.plan.prepare", True)
    at = instant(db)
    if cn.movement_status != "NOT_STARTED" or cn.planning_status == "CANCELLED":
        fail(
            "ROUTE_STUDY_PRE_PICKUP_ONLY",
            "Pre-pickup comparisons require an unpicked consignment. "
            "Use the existing safe-stop recovery workflow in transit.",
        )
    if not at - timedelta(minutes=5) <= payload.departure_at <= at + timedelta(days=30):
        fail(
            "ROUTE_DEPARTURE_INVALID",
            "Use a departure from now through the next 30 days.",
            status=422,
        )
    if payload.fuel_price_per_litre_minor and not price_access(db, ctx, trade):
        fail("FORBIDDEN", "Fuel-cost assumptions require current freight-price access.", status=403)
    snapshot = capture(db, ctx, trade, cn, payload)
    row = RouteStudy(
        trade_id=trade.id,
        consignment_id=cn.id,
        organisation_id=ctx.org_id,
        execution_mode=trade.execution_mode,
        source_mode=payload.source_mode,
        input_json=snapshot,
        input_hash=digest(snapshot),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    job = Job(
        trade_id=trade.id,
        stage=STAGE,
        input_fingerprint=digest({"study": row.id, "input": row.input_hash}),
        pipeline_version=ENGINE_VERSION,
        schema_version="FREIGHT_ROUTE_STUDY_V1",
        configuration_hash=digest(payload.weights.model_dump()),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"study_id": row.id, "consignment_id": cn.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    row.job_id = job.id
    db.add(Outbox(job_id=job.id))
    record(db, ctx, "FREIGHT_ROUTE_STUDY_QUEUED", row, trade, cn)
    return {"id": row.id, "job_state": "QUEUED"}


def exact(db, ctx, ident, permission="tradetwin.read", lock=False):
    row = exists(db, RouteStudy, ident)
    trade, cn = planning(db, ctx, row.consignment_id, permission, lock)
    if row.organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Route comparison not found.", status=404)
    return row, trade, cn


def process(sessions, lease):
    with sessions() as db:
        job, _ = queue.leased(db, *lease, lock=False)
        ctx = queue.job_context(db, job)
        row, _, _ = exact(db, ctx, job.request_json["study_id"], "tradetwin.plan.prepare")
        if digest(row.input_json) != row.input_hash:
            fail(
                "ROUTE_INPUT_INTEGRITY_FAILED", "The captured route inputs failed integrity checks."
            )
        snapshot = deepcopy(row.input_json)
    # No database session, trade lock or lease-row lock is held during network I/O.
    return evaluate(snapshot)


def complete(db, ctx, job, output):
    row, trade, cn = exact(db, ctx, job.request_json["study_id"], "tradetwin.plan.prepare", True)
    if row.job_state != "QUEUED":
        return
    current = capture(db, ctx, trade, cn, StudyInput.model_validate(row.input_json["request"]))
    stale = current["dependency_hash"] != row.input_json["dependency_hash"]
    row.checked_at = instant(db)
    row.valid_until = row.checked_at + timedelta(minutes=15)
    for pack in output["policy_packs"]:
        if pack.get("valid_until"):
            from datetime import datetime

            row.valid_until = min(row.valid_until, datetime.fromisoformat(pack["valid_until"]))
    row.result_json, row.result_hash = output, digest(output)
    row.job_state = "COMPLETED_STALE" if stale else "COMPLETED"
    record(db, ctx, "FREIGHT_ROUTE_STUDY_COMPLETED", row, trade, cn)


def mark_failed(db, job):
    row = db.get(RouteStudy, job.request_json["study_id"])
    if row and row.job_state == "QUEUED":
        row.job_state = "FAILED"


def read(db, ctx, ident):
    row, trade, cn = exact(db, ctx, ident)
    job = db.get(Job, row.job_id)
    freshness = "NOT_EVALUATED"
    if row.result_json:
        try:
            current = capture(
                db, ctx, trade, cn, StudyInput.model_validate(row.input_json["request"])
            )
            freshness = (
                "CURRENT"
                if row.job_state == "COMPLETED"
                and current["dependency_hash"] == row.input_json["dependency_hash"]
                and instant(db) < aware(row.valid_until)
                else "STALE"
            )
        except TradeError:
            freshness = "STALE"
    result = deepcopy(row.result_json)
    visible_price = price_access(db, ctx, trade)
    if result:
        from app.corridor.service import event_visible

        for route in result["candidates"]:
            route["incident_impacts"] = [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"event_hash", "policy_hash"}
                }
                if event_visible(db, ctx, item)
                else {
                    "outcome": item["outcome"],
                    "effect": item["effect"],
                    "headline": "Restricted operational evidence",
                    "source_reference": None,
                    "limitations": ["Current profile cannot read the source details."],
                }
                for item in route["incident_impacts"]
            ]
            if not visible_price:
                route.pop("fuel_estimate_minor", None)
        if freshness != "CURRENT":
            result["comparison"]["best_candidate_id"] = None
            result["comparison"]["comparison_status"] = "HISTORICAL_REQUIRES_REFRESH"
    return {
        "schema_version": "FREIGHT_ROUTE_STUDY_V1",
        "id": row.id,
        "consignment_id": row.consignment_id,
        "job_state": row.job_state if row.job_state != "QUEUED" else job.status,
        "error_code": job.last_error_code,
        "freshness": freshness,
        "checked_at": aware(row.checked_at).isoformat() if row.checked_at else None,
        "valid_until": aware(row.valid_until).isoformat() if row.valid_until else None,
        "source_mode": row.source_mode,
        "execution_mode": row.execution_mode,
        "result": result,
        "price_visible": visible_price,
        "public_fingerprint_short": digest(result)[:12] if result else None,
    }


def listing(db, ctx, ident):
    planning(db, ctx, ident)
    return [
        {
            "id": row.id,
            "job_state": row.job_state,
            "source_mode": row.source_mode,
            "created_at": aware(row.created_at).isoformat(),
        }
        for row in db.scalars(
            select(RouteStudy)
            .where(RouteStudy.consignment_id == ident, RouteStudy.organisation_id == ctx.org_id)
            .order_by(RouteStudy.created_at.desc(), RouteStudy.id.desc())
            .limit(20)
        )
    ]
