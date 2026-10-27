"""Transactional outbox, expiring leases, retry history, and CAS publication."""

import os
import secrets
from datetime import timedelta

from sqlalchemy import or_, select

from app.demo_center import jobs as demo_jobs
from app.operations.access import exists, fail, lock_trade
from app.product import jobs as product_jobs
from app.trades.access import aware
from app.trades.models import User, now, uid
from app.trades.terms import digest
from app.trades.transactions import Context

from . import access
from .context import input_context
from .ledger import record, result, touch
from .models import (
    Artifact,
    Asset,
    Attempt,
    Document,
    Extraction,
    FactRevision,
    Job,
    Observation,
    Outbox,
    Page,
    Version,
)

PIPELINE = "PH3_PIPELINE_V1"
TERMINAL = {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}


def configuration():
    return {
        "pipeline": PIPELINE,
        "max_pages": int(os.getenv("DOCUMENT_MAX_PAGES", "100")),
        "max_text": int(os.getenv("DOCUMENT_MAX_TEXT_CHARS", "1000000")),
        "max_image_pixels": int(os.getenv("DOCUMENT_MAX_IMAGE_PIXELS", "25000000")),
        "max_render_pixels": int(os.getenv("DOCUMENT_MAX_RENDER_PIXELS", "10000000")),
        "ocr_engine": os.getenv("DOCUMENT_OCR_ENGINE", "disabled"),
    }


def enqueue(db, ctx, version, doc, stage, request, reprocess=False):
    nonce = uid() if reprocess else None
    fingerprint = digest(
        {
            "version_id": version.id,
            "source": version.source_manifest_hash,
            "stage": stage,
            "schema": "PH3_CANONICAL_V1",
            "configuration": configuration(),
            "request": request,
            "nonce": nonce,
        }
    )
    existing = db.scalar(select(Job).where(Job.input_fingerprint == fingerprint))
    if existing:
        return existing
    row = Job(
        id=uid(),
        document_version_id=version.id,
        stage=stage,
        input_fingerprint=fingerprint,
        pipeline_version=PIPELINE,
        schema_version="PH3_CANONICAL_V1",
        configuration_hash=digest(configuration()),
        reprocessing_nonce=nonce,
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json=request,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    db.add(Outbox(job_id=row.id))
    record(
        db,
        ctx,
        "DOCUMENT_JOB_QUEUED",
        doc,
        version,
        {"job_id": row.id, "stage": stage, "input_fingerprint": fingerprint},
    )
    return row


def processing(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.process", True)
    clean_assets(db, version)
    if payload.strategy == "SIMULATION_FIXTURE" and doc.execution_mode != "SIMULATION":
        fail(
            "FORBIDDEN", "Simulation extraction is unavailable for production evidence.", status=403
        )
    row = enqueue(
        db, ctx, version, doc, payload.stage, {"strategy": payload.strategy}, payload.reprocess
    )
    return {
        "job_id": row.id,
        "status": row.status,
        "document_id": doc.id,
        "status_url": f"/api/v1/document-processing-jobs/{row.id}",
        "execution_mode": doc.execution_mode,
    }


def clean_assets(db, version):
    from app.operations.models import Attachment

    for asset in db.scalars(select(Asset).where(Asset.document_version_id == version.id)):
        attachment = db.get(Attachment, asset.attachment_id)
        if attachment.security_state != "CLEAN" or attachment.sha256 != asset.asset_sha256:
            fail(
                "ATTACHMENT_NOT_CLEAN",
                "Source asset no longer passes its security/integrity checks.",
            )


def claim(db, worker, job_id=None):
    instant = now()
    query = (
        select(Job)
        .where(
            or_(
                (Job.status == "QUEUED")
                & or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= instant),
                (Job.status == "RUNNING") & (Job.lease_expires_at < instant),
            )
        )
        .order_by(Job.created_at)
    )
    if job_id:
        query = query.where(Job.id == str(job_id))
    row = db.scalar(query.limit(1))
    if not row:
        return None
    requester = db.get(User, row.requested_by_user_id)
    if not requester or (not requester.active and row.stage != "PROJECT_MOVEMENT"):
        row.status, row.last_error_code, row.finished_at = "FAILED", "ACCESS_REVOKED", instant
        if row.stage in product_jobs.STAGES:
            product_jobs.mark(db, row, "FAILED")
        if row.stage in demo_jobs.STAGES:
            demo_jobs.mark(db, row, "FAILED")
        if row.stage == "EVAL_COMPLIANCE":
            from app.compliance.models import Evaluation

            evaluation = db.get(Evaluation, row.request_json["evaluation_id"])
            evaluation.job_state, evaluation.decision = "FAILED", "BLOCKED"
        if row.stage == "FREIGHT_ROUTE_STUDY":
            from app.freight_routes.jobs import mark_failed

            mark_failed(db, row)
        db.commit()
        return None
    if row.stage in product_jobs.STAGES:
        product_jobs.lock(db, row)
    elif row.stage in demo_jobs.STAGES:
        demo_jobs.lock(db, row)
    elif row.stage in {
        "EVAL_COMPLIANCE",
        "PROJECT_MOVEMENT",
        "TRADETWIN_RUN",
        "ROUTE_GENERATION",
        "FREIGHT_ROUTE_STUDY",
    }:
        lock_trade(db, row.trade_id)
    else:
        version = db.get(Version, row.document_version_id)
        lock_trade(db, db.get(Document, version.document_id).trade_id)
    row = db.scalar(
        query.where(Job.id == row.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if not row:
        return None
    if row.current_attempt_id:
        previous = db.get(Attempt, row.current_attempt_id)
        previous.status, previous.finished_at = "LEASE_LOST", instant
    if row.attempt_count >= (1 if row.stage in demo_jobs.STAGES else 3):
        row.status, row.last_error_code, row.finished_at = "FAILED", "ATTEMPTS_EXHAUSTED", instant
        if row.stage in product_jobs.STAGES:
            product_jobs.mark(db, row, "FAILED")
        if row.stage in demo_jobs.STAGES:
            demo_jobs.mark(db, row, "FAILED")
        if row.stage == "FREIGHT_ROUTE_STUDY":
            from app.freight_routes.jobs import mark_failed

            mark_failed(db, row)
        db.commit()
        return None
    attempt = Attempt(
        id=uid(),
        job_id=row.id,
        attempt_number=row.attempt_count + 1,
        worker_reference=worker,
        lease_token=secrets.token_urlsafe(32),
        heartbeat_at=instant,
    )
    db.add(attempt)
    row.attempt_count += 1
    row.current_attempt_id, row.status = attempt.id, "RUNNING"
    row.lease_expires_at = instant + timedelta(seconds=120)
    row.row_version += 1
    db.flush()
    ctx = Context(db.get(User, row.requested_by_user_id), row.requested_by_organization_id, uid())
    if row.stage in product_jobs.STAGES:
        product_jobs.mark(db, row, "RUNNING")
    elif row.stage in demo_jobs.STAGES:
        demo_jobs.mark(db, row, "RUNNING")
    elif row.stage in {
        "EVAL_COMPLIANCE",
        "PROJECT_MOVEMENT",
        "TRADETWIN_RUN",
        "ROUTE_GENERATION",
        "FREIGHT_ROUTE_STUDY",
    }:
        from app.compliance.ledger import record as compliance_record

        compliance_record(db, ctx, "COMPLIANCE_ATTEMPT_STARTED", row, row.trade_id)
    else:
        doc = db.get(Document, db.get(Version, row.document_version_id).document_id)
        record(
            db,
            ctx,
            "DOCUMENT_ATTEMPT_STARTED",
            doc,
            detail={"job_id": row.id, "attempt_id": attempt.id},
        )
    db.commit()
    return row.id, attempt.id, attempt.lease_token


def job_context(db, job):
    user = db.get(User, job.requested_by_user_id)
    if not user or (not user.active and job.stage != "PROJECT_MOVEMENT"):
        fail("FORBIDDEN", "Requesting account is inactive.", status=403)
    return Context(user, job.requested_by_organization_id, uid())


def leased(db, job_id, attempt_id, token, lock=True):
    query = select(Job).where(Job.id == str(job_id))
    if lock:
        basis = db.scalar(query)
        if not basis:
            fail("JOB_ALREADY_TERMINAL", "Job no longer exists.")
        if basis.stage in product_jobs.STAGES:
            product_jobs.lock(db, basis)
        elif basis.stage in demo_jobs.STAGES:
            demo_jobs.lock(db, basis)
        elif basis.stage in {
            "EVAL_COMPLIANCE",
            "PROJECT_MOVEMENT",
            "TRADETWIN_RUN",
            "ROUTE_GENERATION",
            "FREIGHT_ROUTE_STUDY",
        }:
            lock_trade(db, basis.trade_id)
        else:
            version = db.get(Version, basis.document_version_id)
            lock_trade(db, db.get(Document, version.document_id).trade_id)
        query = query.with_for_update().execution_options(populate_existing=True)
    job = db.scalar(query)
    attempt = db.get(Attempt, str(attempt_id))
    if not job or not attempt or job.current_attempt_id != attempt.id or job.status != "RUNNING":
        fail("JOB_ALREADY_TERMINAL", "Attempt no longer owns a running job.")
    if (
        not secrets.compare_digest(attempt.lease_token, token)
        or aware(job.lease_expires_at) <= now()
    ):
        fail("JOB_ALREADY_TERMINAL", "Worker lease was lost.")
    return job, attempt


def heartbeat(db, job_id, attempt_id, token):
    job, attempt = leased(db, job_id, attempt_id, token)
    job.lease_expires_at = now() + timedelta(seconds=120)
    attempt.heartbeat_at = now()
    db.commit()


def cancel(db, ctx, ident, payload):
    job = exists(db, Job, ident)
    if job.stage in product_jobs.STAGES:
        product_jobs.lock(db, job)
        product_jobs.view(db, ctx, job)
        if ctx.if_match != f'"{job.row_version}"' or job.status in TERMINAL:
            fail("JOB_ALREADY_TERMINAL", "Job changed or already finished.", status=412)
        job.status, job.cancelled_at, job.finished_at = "CANCELLED", now(), now()
        job.row_version += 1
        product_jobs.mark(db, job, "CANCELLED")
        return product_jobs.view(db, ctx, job)
    if job.stage == "PROJECT_MOVEMENT":
        from app.compliance.context import access as compliance_access

        compliance_access(db, ctx, job.request_json["consignment_id"])
        fail("FORBIDDEN", "Committed movement projections cannot be cancelled.", status=403)
    if job.stage == "EVAL_COMPLIANCE":
        from app.compliance.context import access as compliance_access

        compliance_access(
            db, ctx, job.request_json["consignment_id"], "compliance.evaluate", True, True
        )
    else:
        version, doc, _ = access.version(db, ctx, job.document_version_id, "document.process", True)
    if ctx.if_match != f'"{job.row_version}"':
        fail("REVIEW_HEAD_CHANGED", "Processing job changed. Reload its current ETag.")
    if job.status in TERMINAL:
        fail("JOB_ALREADY_TERMINAL", "Processing job has already finished.")
    job.status, job.cancelled_at, job.finished_at = "CANCELLED", now(), now()
    job.row_version += 1
    if job.current_attempt_id:
        attempt = db.get(Attempt, job.current_attempt_id)
        attempt.status, attempt.finished_at = "CANCELLED", now()
    if job.stage == "EVAL_COMPLIANCE":
        from app.compliance.ledger import record as compliance_record
        from app.compliance.models import Evaluation

        evaluation = db.get(Evaluation, job.request_json["evaluation_id"])
        evaluation.job_state, evaluation.decision = "CANCELLED", "BLOCKED"
        compliance_record(db, ctx, "COMPLIANCE_JOB_CANCELLED", job, job.trade_id)
    else:
        record(
            db,
            ctx,
            "DOCUMENT_JOB_CANCELLED",
            doc,
            version,
            {"job_id": job.id, "reason": payload.reason},
        )
    return job_view(db, ctx, job)


def job_view(db, ctx, row):
    if row.stage in demo_jobs.STAGES:
        from app.demo_center.service import owned

        owned(db, ctx, row.request_json["launch_id"])
        return {"id": row.id, "status": row.status, "last_error_code": row.last_error_code}
    if row.stage in product_jobs.STAGES:
        return product_jobs.view(db, ctx, row)
    if row.stage in {"EVAL_COMPLIANCE", "PROJECT_MOVEMENT"}:
        from app.compliance.context import access as compliance_access

        compliance_access(db, ctx, row.request_json["consignment_id"])
        return {
            "id": row.id,
            "status": row.status,
            "evaluation_id": row.request_json.get("evaluation_id"),
            "last_error_code": row.last_error_code,
            "etag": f'"{row.row_version}"',
        }
    _, doc, _ = access.version(db, ctx, row.document_version_id)
    access.capture(db, ctx, doc)
    body = result(row, doc)
    body.pop("request_json", None)
    return {
        **body,
        "attempts": [
            result(a) for a in db.scalars(select(Attempt).where(Attempt.job_id == row.id))
        ],
        "extraction_run_ids": list(
            db.scalars(
                select(Extraction.id)
                .join(Attempt, Attempt.id == Extraction.job_attempt_id)
                .where(Attempt.job_id == row.id)
            )
        ),
    }


def failed(db, lease, code):
    job, attempt = leased(db, *lease)
    attempt.status, attempt.finished_at, attempt.error_code = "FAILED", now(), code
    attempt.redacted_error_summary = (
        "Processing failed; original evidence and earlier attempts are preserved."
    )
    job.last_error_code = code
    retryable = job.stage not in demo_jobs.STAGES and code in {
        "STORAGE_UNAVAILABLE",
        "PROVIDER_UNAVAILABLE",
        "STAGE_TIMEOUT",
    }
    job.status = "QUEUED" if retryable and job.attempt_count < 3 else "FAILED"
    job.next_attempt_at = now() + timedelta(
        seconds=int(os.getenv("DOCUMENT_JOB_BACKOFF_SECONDS", "10")) * job.attempt_count
    )
    if job.status == "FAILED":
        job.finished_at = now()
    if job.stage in demo_jobs.STAGES:
        demo_jobs.mark(db, job, job.status)
        db.commit()
        return
    if job.stage in product_jobs.STAGES:
        product_jobs.mark(db, job, job.status)
        db.commit()
        return
    if job.stage == "FREIGHT_ROUTE_STUDY":
        if job.status == "FAILED":
            from app.freight_routes.jobs import mark_failed

            mark_failed(db, job)
        db.commit()
        return
    if job.stage in {"TRADETWIN_RUN", "ROUTE_GENERATION"}:
        from app.freight.models import Generation, Run

        model, key = (
            (Run, "run_id") if job.stage == "TRADETWIN_RUN" else (Generation, "generation_id")
        )
        row = db.get(model, job.request_json[key])
        if row.job_state not in {"COMPLETED", "FAILED", "CANCELLED"} and job.status == "FAILED":
            row.job_state = "FAILED"
        from app.compliance.ledger import record as freight_record

        freight_record(
            db, job_context(db, job), "FREIGHT_JOB_FAILED", job, job.trade_id, {"error_code": code}
        )
        db.commit()
        return
    if job.stage in {"EVAL_COMPLIANCE", "PROJECT_MOVEMENT"}:
        from app.compliance.ledger import record as compliance_record
        from app.compliance.models import Evaluation

        evaluation = (
            db.get(Evaluation, job.request_json["evaluation_id"])
            if job.stage == "EVAL_COMPLIANCE"
            else None
        )
        if job.status == "FAILED" and evaluation:
            evaluation.job_state = "FAILED"
        compliance_record(
            db,
            Context(
                db.get(User, job.requested_by_user_id), job.requested_by_organization_id, uid()
            ),
            "COMPLIANCE_ATTEMPT_FAILED",
            job,
            job.trade_id,
            {"error_code": code},
        )
        db.commit()
        return
    doc = db.get(Document, db.get(Version, job.document_version_id).document_id)
    record(
        db,
        Context(db.get(User, job.requested_by_user_id), job.requested_by_organization_id, uid()),
        "DOCUMENT_ATTEMPT_FAILED",
        doc,
        detail={"job_id": job.id, "attempt_id": attempt.id, "error_code": code},
    )
    db.commit()


def finish_extraction(db, lease, output):
    from .schemas import CanonicalDocument, SourceLocator

    job, attempt = leased(db, *lease)
    ctx = job_context(db, job)
    version, doc, _ = access.version(db, ctx, job.document_version_id, "document.process", True)
    clean_assets(db, version)
    if output.get("engine_kind") == "SIMULATION_FIXTURE" and doc.execution_mode != "SIMULATION":
        fail("FORBIDDEN", "Simulation extraction cannot process production evidence.", status=403)
    artifacts = {}
    for artifact in output.get("artifacts", []):
        if (
            artifact["document_version_id"] != version.id
            or artifact["job_attempt_id"] != attempt.id
        ):
            fail("OBSERVATION_SOURCE_MISMATCH", "Derived artifact belongs to another attempt.")
        row = Artifact(**artifact)
        artifacts[row.id] = row
        db.add(row)
    for page in output.get("pages", []):
        if page["page_image_artifact_id"] not in artifacts:
            fail("OBSERVATION_SOURCE_MISMATCH", "Page image artifact is absent.")
        db.add(Page(document_version_id=version.id, **page))
    from .models import FileMetadata

    for metadata in output.get("file_metadata", []):
        db.add(FileMetadata(document_version_id=version.id, job_attempt_id=attempt.id, **metadata))
    if job.stage == "EXTRACT":
        canonical = CanonicalDocument.model_validate(output["canonical_document"]).model_dump(
            mode="json"
        )
        from .models import LineIdentity

        row_keys = list(
            dict.fromkeys(o["row_key"] for o in output.get("observations", []) if o.get("row_key"))
        )
        for index, line in enumerate(canonical["lines"]):
            existing = db.get(LineIdentity, line["document_line_ref"])
            if existing and existing.document_version_id != version.id:
                fail("OBSERVATION_SOURCE_MISMATCH", "Proposed line belongs to another source.")
            if not existing:
                db.add(
                    LineIdentity(
                        id=line["document_line_ref"],
                        document_version_id=version.id,
                        reason="Server extraction proposal",
                        source_row_key=row_keys[index] if index < len(row_keys) else None,
                    )
                )
        run = Extraction(
            id=uid(),
            job_attempt_id=attempt.id,
            document_version_id=version.id,
            source_manifest_hash=version.source_manifest_hash,
            engine_kind=output["engine_kind"],
            engine_name=output["engine_name"],
            engine_version=output["engine_version"],
            schema_version=job.schema_version,
            status=output["status"],
            finished_at=now(),
            error_code=output.get("error_code"),
            proposed_document_json=canonical,
        )
        db.add(run)
        db.flush()
        for value in output.get("observations", []):
            data = dict(value)
            if data["field_path"].endswith("_at") and data.get("normalised_value_json") is not None:
                from datetime import datetime

                from app.trades.schemas import utc

                normalized = (
                    utc(datetime.fromisoformat(str(data["normalised_value_json"])))
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                if normalized != data["normalised_value_json"]:
                    data["normalisation_warnings_json"] = [
                        *data.get("normalisation_warnings_json", []),
                        "UTC_TIMESTAMP_CONVERSION",
                    ]
                data["normalised_value_json"] = normalized
            from .ledger import field_path

            if not field_path(
                data["field_path"].replace(
                    "lines.*.", "lines.00000000-0000-4000-8000-000000000001."
                )
            ):
                fail("INVALID_EXTRACTION_RESULT", "Extraction contains an unknown field path.")
            if data.get("provider_confidence") is not None:
                from decimal import Decimal

                confidence = Decimal(str(data["provider_confidence"]))
                if not confidence.is_finite() or not 0 <= confidence <= 1:
                    fail(
                        "INVALID_EXTRACTION_RESULT",
                        "Confidence must be null or between zero and one.",
                    )
            data["source_locator_json"] = SourceLocator.model_validate(
                data["source_locator_json"]
            ).model_dump(mode="json")
            from .review import locator

            locator(db, version.id, data["source_locator_json"])
            db.add(Observation(id=uid(), extraction_run_id=run.id, **data))
        if version.id == doc.current_version_id and not doc.effective_fact_revision_id:
            old = (
                db.get(FactRevision, doc.latest_draft_fact_revision_id)
                if doc.latest_draft_fact_revision_id
                else None
            )
            if not old or old.created_by_user_id is None:
                from sqlalchemy import func

                number = (
                    db.scalar(
                        select(func.max(FactRevision.revision_number)).where(
                            FactRevision.document_version_id == version.id
                        )
                    )
                    or 0
                ) + 1
                draft = FactRevision(
                    id=uid(),
                    document_version_id=version.id,
                    extraction_run_id=run.id,
                    revision_number=number,
                    canonical_document_json=canonical,
                    content_hash=digest({"proposed": canonical, "run_id": run.id}),
                )
                db.add(draft)
                doc.latest_draft_fact_revision_id = draft.id
                touch(doc)
    job.status, job.finished_at = output["status"], now()
    attempt.status, attempt.finished_at = output["status"], now()
    record(
        db,
        ctx,
        "DOCUMENT_PROCESSING_COMPLETED",
        doc,
        version,
        {
            "job_id": job.id,
            "attempt_id": attempt.id,
            "status": job.status,
            "dispatch_readiness": "NOT_ASSESSED",
        },
    )
    db.commit()


def assessment(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.check", True)
    fact = exists(db, FactRevision, payload.fact_revision_id)
    if not access.full_capture(db, ctx, doc) and fact.id != doc.effective_fact_revision_id:
        fail("FORBIDDEN", "This grant shares submitted values only.", status=403)
    if fact.document_version_id != version.id:
        fail("OBSERVATION_SOURCE_MISMATCH", "Comparison fact revision belongs to another source.")
    for cn in payload.consignment_ids:
        trade, _, _ = access.consignment(db, ctx, cn)
        if trade.id != doc.trade_id:
            fail("NOT_FOUND", "Consignment not found.", status=404)
    for related in payload.related_document_version_ids:
        _, other, _ = access.version(db, ctx, related)
        if other.trade_id != doc.trade_id:
            fail("NOT_FOUND", "Related source not found.", status=404)
    request = payload.model_dump(mode="json")
    if (
        fact.id not in {doc.effective_fact_revision_id, doc.latest_draft_fact_revision_id}
        or version.id != doc.current_version_id
    ):
        fail("ASSESSMENT_INPUT_STALE", "Select the current effective review or current draft.")
    request["fact_selector"] = "EFFECTIVE" if fact.id == doc.effective_fact_revision_id else "DRAFT"
    request["input_context"] = input_context(db, doc, request)
    from .checks import duplicate_candidates

    evaluated_at = now()
    boundaries = [
        evaluated_at
        + timedelta(seconds=int(os.getenv("DOCUMENT_VERIFICATION_TTL_SECONDS", "3600")))
    ]
    from datetime import datetime

    for key in ("valid_from_at", "valid_until_at"):
        declared = fact.canonical_document_json["eway_bill"].get(key)
        if declared and aware(datetime.fromisoformat(declared)) > evaluated_at:
            boundaries.append(aware(datetime.fromisoformat(declared)))
    request["input_context"]["assessment_observation"] = {
        "checked_at": evaluated_at.isoformat(),
        "fresh_until": min(boundaries).isoformat(),
        "duplicate_candidates": duplicate_candidates(db, ctx, doc),
    }
    if payload.mapping_revision_id:
        from .models import MappingRevision

        mapping = exists(db, MappingRevision, payload.mapping_revision_id)
        if mapping.document_id != doc.id or mapping.fact_revision_id != fact.id:
            fail("ASSESSMENT_INPUT_STALE", "Mapping does not describe these reviewed facts.")
        from .context import mapping_freshness

        if mapping_freshness(db, doc, mapping.source_context_json) != "CURRENT":
            fail(
                "ASSESSMENT_INPUT_STALE",
                "Mapping targets changed; confirm a new mapping revision first.",
            )
    row = enqueue(db, ctx, version, doc, "COMPARE", request)
    return {
        "job_id": row.id,
        "status": row.status,
        "status_url": f"/api/v1/document-processing-jobs/{row.id}",
        "dispatch_readiness": "NOT_ASSESSED",
    }
