"""Expiring, recipient-only decision manifests, never raw documents or provider payloads."""

from datetime import timedelta

from sqlalchemy import func, select

from app.compliance.clock import aware, instant
from app.document_desk.models import Job, Outbox
from app.freight.models import Commitment, Dataset, Quote, Run, Template
from app.operations.access import exists, fail
from app.trades.terms import digest

from . import replay
from .models import Bundle


def access(db, ctx, row):
    if row.recipient_user_id != ctx.user.id or row.recipient_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Evidence bundle not found.", status=404)
    if row.revoked_at or instant(db) >= aware(row.expires_at):
        fail("BUNDLE_EXPIRED", "Evidence access expired or was revoked.", status=410)
    return replay.subject(db, ctx, row.subject_type, row.subject_id, "evidence.bundle.request")


def request(db, ctx, ident, payload):
    subject, trade = replay.subject(
        db, ctx, payload.subject_type, payload.subject_id, "evidence.bundle.request"
    )
    recipient = payload.recipient_reference
    if recipient and (
        str(recipient.user_id) != ctx.user.id or str(recipient.organisation_id) != ctx.org_id
    ):
        fail("FORBIDDEN", "A bundle cannot grant access to another principal.", status=403)
    if payload.visibility == "PUBLIC_SYNTHETIC_DEMO":
        # Execution mode alone does not certify that every uploaded source is synthetic.
        fail(
            "SYNTHETIC_PROVENANCE_REQUIRED",
            "Public export requires registered synthetic provenance, not merely simulation mode.",
            status=422,
        )
    if isinstance(subject, Run) and any(
        not source["dataset"].get("export_allowed")
        for source in subject.input_json.get("sources", [])
    ):
        fail(
            "SOURCE_EXPORT_NOT_PERMITTED", "A retained source licence prohibits export.", status=403
        )
    if isinstance(subject, Commitment):
        quote = exists(db, Quote, subject.quote_revision_id)
        template = exists(db, Template, quote.route_template_revision_id)
        dataset = exists(db, Dataset, template.dataset_revision_id)
        if not dataset.dataset_json.get("export_allowed"):
            fail(
                "SOURCE_EXPORT_NOT_PERMITTED",
                "A retained source licence prohibits export.",
                status=403,
            )
    count = db.scalar(
        select(func.count())
        .select_from(Bundle)
        .where(Bundle.recipient_user_id == ctx.user.id, Bundle.status == "QUEUED")
    )
    if count >= 2:
        fail("JOB_RATE_LIMITED", "Finish an outstanding evidence export first.", status=429)
    row = Bundle(
        trade_id=trade.id,
        subject_type=payload.subject_type,
        subject_id=subject.id,
        recipient_user_id=ctx.user.id,
        recipient_organisation_id=ctx.org_id,
        visibility=payload.visibility,
        expires_at=instant(db) + timedelta(hours=1),
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    job = Job(
        trade_id=trade.id,
        stage="EVIDENCE_BUNDLE",
        input_fingerprint=digest({"bundle_id": row.id}),
        pipeline_version="EVIDENCE_MANIFEST_V1",
        schema_version="EVIDENCE_BUNDLE_V1",
        configuration_hash=digest({"visibility": row.visibility}),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"bundle_id": row.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    row.job_id = job.id
    db.add(Outbox(job_id=job.id))
    return {"id": row.id, "status": "QUEUED", "expires_at": aware(row.expires_at).isoformat()}


def complete(db, ctx, ident):
    row = exists(db, Bundle, ident)
    subject, _ = access(db, ctx, row)
    if row.status == "READY":
        return
    fingerprint, engine, as_of = replay.identity(db, subject, row.subject_type)
    # Do not duplicate confidential snapshots into an unencrypted second artifact store.
    value = {
        "schema_version": "EVIDENCE_MANIFEST_V1",
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "recorded_as_of": aware(as_of).isoformat(),
        "engine_version": engine,
        "retained_manifest_hash": fingerprint,
        "export_kind": "REFERENCE_MANIFEST_ONLY",
        "raw_documents_included": False,
        "source_payloads_included": False,
        "limitations": [
            "Hashes check retained content, not authenticity, settlement or clearance.",
            "This bounded export is not a full signed evidence package.",
        ],
    }
    row.manifest_json, row.manifest_hash, row.status = value, digest(value), "READY"


def read(db, ctx, ident, download=False):
    row = exists(db, Bundle, ident)
    access(db, ctx, row)
    if download and row.status != "READY":
        fail("JOB_NOT_READY", "Evidence manifest is not ready.")
    value = {
        "id": row.id,
        "status": row.status,
        "expires_at": aware(row.expires_at).isoformat(),
        "download_url": f"/api/v1/evidence/bundles/{row.id}/download"
        if row.status == "READY"
        else None,
    }
    if download:
        if row.manifest_hash != digest(row.manifest_json):
            fail("EVIDENCE_INTEGRITY_FAILED", "Retained manifest integrity check failed.")
        value["manifest"] = row.manifest_json
        value["manifest_hash"] = row.manifest_hash
    return value
