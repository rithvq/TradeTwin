"""Reuse the leased transactional outbox, including revocation and stale-worker checks."""

from app.operations.access import exists, fail, lock_trade
from app.trades.context_locks import registry_lock

from . import assurance, bundles, replay
from .models import Bundle, ReadinessRun, ReplayRequest

STAGES = {"DECISION_REPLAY", "READINESS_CHECK", "EVIDENCE_BUNDLE"}
RESOURCES = {
    "DECISION_REPLAY": (ReplayRequest, "replay_request_id", "job_state"),
    "READINESS_CHECK": (ReadinessRun, "readiness_run_id", "job_state"),
    "EVIDENCE_BUNDLE": (Bundle, "bundle_id", "status"),
}


def lock(db, job):
    if job.trade_id:
        lock_trade(db, job.trade_id)
    else:
        registry_lock(db, exclusive=True)


def complete(db, ctx, job):
    if job.stage == "DECISION_REPLAY":
        replay.complete(db, ctx, job.request_json["replay_request_id"])
    elif job.stage == "EVIDENCE_BUNDLE":
        bundles.complete(db, ctx, job.request_json["bundle_id"])
    else:
        assurance.complete(db, ctx, job.request_json["readiness_run_id"])


def mark(db, job, status):
    model, key, attribute = RESOURCES[job.stage]
    row = exists(db, model, job.request_json[key])
    if getattr(row, attribute) not in {"COMPLETED", "READY"}:
        setattr(row, attribute, status)


def view(db, ctx, job):
    if job.requested_by_user_id != ctx.user.id or job.requested_by_organization_id != ctx.org_id:
        fail("NOT_FOUND", "Processing job not found.", status=404)
    if job.stage == "DECISION_REPLAY":
        replay.read(db, ctx, job.request_json["replay_request_id"])
    elif job.stage == "EVIDENCE_BUNDLE":
        bundles.read(db, ctx, job.request_json["bundle_id"])
    else:
        assurance.read(db, ctx, job.request_json["readiness_run_id"])
    return {
        "id": job.id,
        "status": job.status,
        "last_error_code": job.last_error_code,
        "etag": f'"{job.row_version}"',
    }
