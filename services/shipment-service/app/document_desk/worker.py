"""Durable outbox/Redis worker. DB leases remain authoritative during queue outages."""

import os
import socket
import threading
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from tradetwin_security.document_worker import headers as worker_headers

from app.database import SessionLocal, engine
from app.trades.errors import TradeError
from app.trades.migrate import migrate
from app.trades.models import now

from . import access, checks, jobs
from .ledger import record
from .models import (
    Artifact,
    FactRevision,
    Job,
    MappingRevision,
    Outbox,
    VerificationCheck,
    VerificationResult,
)


def publish_outbox(sessions):
    import redis

    client = redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    with sessions() as db:
        for event in db.scalars(
            select(Outbox)
            .where(Outbox.published_at.is_(None))
            .limit(100)
            .with_for_update(skip_locked=True)
        ):
            event.delivery_attempts += 1
            try:
                client.lpush("tradetwin:document-jobs", event.job_id)
                event.published_at = now()
            except redis.RedisError:
                break
        db.commit()
    client.close()


def complete(db, lease, output):
    job, attempt = jobs.leased(db, *lease)
    ctx = jobs.job_context(db, job)
    if job.stage == "ROUTE_GENERATION":
        from app.freight.routing import complete_generation

        complete_generation(db, ctx, job.request_json["generation_id"])
        job.status, job.finished_at = "SUCCEEDED", now()
        attempt.status, attempt.finished_at = "SUCCEEDED", now()
        db.commit()
        return
    if job.stage == "TRADETWIN_RUN":
        from app.freight.runs import complete as complete_run

        complete_run(db, ctx, job.request_json["run_id"])
        job.status, job.finished_at = "SUCCEEDED", now()
        attempt.status, attempt.finished_at = "SUCCEEDED", now()
        db.commit()
        return
    if job.stage == "PROJECT_MOVEMENT":
        from app.compliance.projection import deliver

        deliver(db, ctx, job)
        job.status, job.finished_at = "SUCCEEDED", now()
        attempt.status, attempt.finished_at = "SUCCEEDED", now()
        db.commit()
        return
    if job.stage == "EVAL_COMPLIANCE":
        from app.compliance.evaluations import complete as evaluate_compliance

        evaluate_compliance(db, ctx, job.request_json["evaluation_id"])
        job.status, job.finished_at = "SUCCEEDED", now()
        attempt.status, attempt.finished_at = "SUCCEEDED", now()
        db.commit()
        return
    permission = "document.check" if job.stage == "COMPARE" else "document.verify.request"
    version, doc, _ = access.version(db, ctx, job.document_version_id, permission, True)
    if job.stage == "COMPARE":
        fact = db.get(FactRevision, job.request_json["fact_revision_id"])
        mapping = (
            db.get(MappingRevision, job.request_json.get("mapping_revision_id"))
            if job.request_json.get("mapping_revision_id")
            else None
        )
        for related in job.request_json.get("related_document_version_ids", []):
            access.version(db, ctx, related)
        ctx.attempt_id = attempt.id
        checks.compare(db, ctx, doc, version, fact, mapping, job.request_json["input_context"])
    else:
        for artifact in output.get("artifacts", []):
            if (
                artifact["document_version_id"] != version.id
                or artifact["job_attempt_id"] != attempt.id
            ):
                access.fail(
                    "OBSERVATION_SOURCE_MISMATCH",
                    "Verification artifact belongs to another attempt.",
                )
            db.add(Artifact(**artifact))
        check = db.scalar(select(VerificationCheck).where(VerificationCheck.job_id == job.id))
        result = output["verification_result"]
        if result["input_hash"] != check.input_hash:
            access.fail(
                "OBSERVATION_SOURCE_MISMATCH", "Verification response describes different inputs."
            )
        if doc.execution_mode == "PRODUCTION" and result["provider_environment"] != "LIVE":
            result["lookup_outcome"] = "NOT_AUTHORISED"
            result["signature_integrity"] = "KEY_UNAVAILABLE"
        db.add(
            VerificationResult(
                verification_check_id=check.id, job_attempt_id=attempt.id, result_json=result
            )
        )
    job.status, job.finished_at = "SUCCEEDED", now()
    attempt.status, attempt.finished_at = "SUCCEEDED", now()
    record(
        db,
        ctx,
        "DOCUMENT_COMPARISON_COMPLETED"
        if job.stage == "COMPARE"
        else "DOCUMENT_VERIFICATION_OBSERVED",
        doc,
        version,
        {"job_id": job.id, "dispatch_readiness": "NOT_ASSESSED"},
    )
    db.commit()


def run_one(sessions=SessionLocal, job_id=None, processor=None):
    with sessions() as db:
        lease = jobs.claim(db, f"{socket.gethostname()}:{os.getpid()}", job_id)
    if not lease:
        return False
    stop = threading.Event()

    def beat():
        while not stop.wait(20):
            try:
                with sessions() as db:
                    jobs.heartbeat(db, *lease)
                Path(
                    os.getenv("DOCUMENT_WORKER_HEARTBEAT_FILE", "/tmp/document-worker-heartbeat")
                ).write_text(str(time.time()))
            except Exception:
                return

    heartbeat = threading.Thread(target=beat, daemon=True)
    heartbeat.start()
    try:
        with sessions() as db:
            row = db.get(Job, lease[0])
            stage = row.stage
        if stage in {
            "COMPARE",
            "EVAL_COMPLIANCE",
            "PROJECT_MOVEMENT",
            "TRADETWIN_RUN",
            "ROUTE_GENERATION",
        }:
            output = {}
        elif processor:
            output = processor(lease)
        else:
            url = os.getenv("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8013").rstrip("/")
            with httpx.Client(timeout=315) as client:
                response = client.post(
                    f"{url}/internal/document-desk/process",
                    json={"job_id": lease[0], "attempt_id": lease[1], "lease_token": lease[2]},
                    headers=worker_headers(),
                )
                response.raise_for_status()
                output = response.json()
        with sessions() as db:
            if output.get("status") == "FAILED":
                jobs.failed(db, lease, output.get("error_code", "DOCUMENT_PARSE_FAILED"))
            elif stage in {"PREPROCESS", "EXTRACT"}:
                jobs.finish_extraction(db, lease, output)
            else:
                complete(db, lease, output)
    except Exception as exc:
        revoked = isinstance(exc, TradeError) and exc.status in {401, 403, 404}
        revoked = revoked or (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403, 404}
        )
        try:
            with sessions() as db:
                jobs.failed(
                    db,
                    lease,
                    "ACCESS_REVOKED"
                    if revoked
                    else "STORAGE_UNAVAILABLE"
                    if isinstance(exc, httpx.HTTPError)
                    else "INVALID_EXTRACTION_RESULT",
                )
        except Exception:
            # Cancelled/expired leases cannot publish failures either.
            pass
    finally:
        stop.set()
        heartbeat.join(timeout=5)
    return True


def main():
    migrate(engine)
    heartbeat_path = Path(
        os.getenv("DOCUMENT_WORKER_HEARTBEAT_FILE", "/tmp/document-worker-heartbeat")
    )
    while True:
        heartbeat_path.write_text(str(time.time()))
        try:
            publish_outbox(SessionLocal)
            import redis

            with redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), socket_timeout=2
            ) as client:
                ident = client.rpop("tradetwin:document-jobs")
            if ident:
                run_one(job_id=ident.decode())
            run_one()
        except Exception:
            run_one()
        time.sleep(1)


if __name__ == "__main__":
    main()
