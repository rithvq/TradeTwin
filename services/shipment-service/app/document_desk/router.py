from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from tradetwin_security import service_headers

from app.database import get_db
from app.operations.access import exists, fail
from app.operations.models import Assignment, Attachment
from app.trades.schemas import Schema
from app.trades.transactions import context, mutate

from . import access, checks, jobs, mapping, register, review, schemas, verification, views
from .ledger import flatten, result
from .models import (
    AccessGrant,
    Artifact,
    Assessment,
    Asset,
    Connection,
    Extraction,
    FactRevision,
    Finding,
    Job,
    ManualAttestation,
    Observation,
    Page,
    SubjectLink,
    TrustedKey,
    VerificationCheck,
)

router = APIRouter(tags=["Document evidence - Phase 3"])
internal = APIRouter(
    prefix="/internal/document-desk", tags=["Internal document worker"], include_in_schema=False
)


class FixtureImport(Schema):
    attachment_id: UUID
    user_id: UUID
    organization_id: UUID
    fixture_name: str = Field(max_length=100, pattern=r"^[a-z0-9-]+\.(pdf|png|json)$")


@internal.post("/fixture-input")
def fixture_input(payload: FixtureImport, db: Session = Depends(get_db)):
    import os

    from app.operations import attachments
    from app.trades.models import User
    from app.trades.transactions import Context

    row = exists(db, Attachment, payload.attachment_id)
    user = exists(db, User, payload.user_id)
    if not user.active:
        fail("FORBIDDEN", "Development identity is inactive.", status=403)
    ctx = Context(user, str(payload.organization_id), str(payload.attachment_id))
    trade, _ = attachments.access(db, ctx, row, True)
    if trade.execution_mode != "SIMULATION":
        fail("FORBIDDEN", "Development fixtures cannot enter production trades.", status=403)
    if os.getenv("DOCUMENT_DEMO_ENABLED", "false").lower() != "true":
        from app.demo_center.service import fixture_access

        fixture_access(db, user, ctx.org_id, trade)
    return {**result(row), "execution_mode": trade.execution_mode}


def authorize(db, ctx, resource, ident, permission, payload=None):
    if resource == "trade":
        return access.registration_access(
            db, ctx, ident, payload.document_type, payload.initial_consignment_id
        )
    if resource == "organization":
        if ctx.org_id != str(ident):
            fail("FORBIDDEN", "Switch to this organisation.", status=403)
        return access.require(db, ctx.user, ctx.org_id, permission)
    if resource == "document":
        return access.document(db, ctx, ident, permission, True)
    if resource == "version":
        return access.version(db, ctx, ident, permission, True)
    model = {
        "fact": FactRevision,
        "job": Job,
        "finding": Finding,
        "grant": AccessGrant,
        "link": SubjectLink,
    }[resource]
    row = exists(db, model, ident)
    if resource == "job" and row.stage == "PROJECT_MOVEMENT":
        from app.compliance.context import access as compliance_access

        compliance_access(db, ctx, row.request_json["consignment_id"])
        fail("FORBIDDEN", "Committed movement projections cannot be cancelled.", status=403)
    if resource == "job" and row.stage == "EVAL_COMPLIANCE":
        from app.compliance.context import access as compliance_access

        return compliance_access(
            db, ctx, row.request_json["consignment_id"], "compliance.evaluate", True, True
        )
    if resource == "finding":
        row = exists(db, Assessment, row.assessment_run_id)
    return access.version(db, ctx, row.document_version_id, permission, True)


def mutation(path, schema, service, resource, permission, status=200):
    def endpoint(ident: UUID, request: Request, payload: schema, db: Session = Depends(get_db)):
        return mutate(
            request,
            db,
            lambda db, ctx, value: service(db, ctx, str(ident), value),
            payload,
            status=status,
            authorize=lambda db, ctx: authorize(db, ctx, resource, ident, permission, payload),
            conflict_code="IDEMPOTENCY_CONFLICT",
        )

    endpoint.__name__ = "documents_" + path.replace("/", "_").replace("{ident}", "record")
    router.add_api_route(path, endpoint, methods=["POST"], status_code=status)


mutation(
    "/trades/{ident}/documents",
    schemas.Registration,
    register.create,
    "trade",
    "document.register",
    201,
)
mutation(
    "/documents/{ident}/versions",
    schemas.SourceVersion,
    register.version_add,
    "document",
    "document.version.add",
    201,
)
mutation(
    "/documents/{ident}/relationships",
    schemas.RelationshipInput,
    register.relationship,
    "document",
    "document.review.submit",
    201,
)
mutation(
    "/documents/{ident}/archives", schemas.Reason, register.archive, "document", "document.archive"
)
mutation(
    "/document-versions/{ident}/subject-links",
    schemas.SubjectInput,
    register.link_subject,
    "version",
    "document.register",
    201,
)
mutation(
    "/document-versions/{ident}/access-grants",
    schemas.ShareInput,
    register.share,
    "version",
    "document.share",
    201,
)
mutation(
    "/document-subject-links/{ident}/revocations",
    schemas.Reason,
    lambda db, ctx, ident, p: register.revoke(db, ctx, SubjectLink, ident, p),
    "link",
    "document.share",
)
mutation(
    "/document-access-grants/{ident}/revocations",
    schemas.Reason,
    lambda db, ctx, ident, p: register.revoke(db, ctx, AccessGrant, ident, p),
    "grant",
    "document.share",
)
mutation(
    "/document-versions/{ident}/processing-jobs",
    schemas.Processing,
    jobs.processing,
    "version",
    "document.process",
    202,
)
mutation(
    "/document-processing-jobs/{ident}/cancellations",
    schemas.Reason,
    jobs.cancel,
    "job",
    "document.process",
)
mutation(
    "/document-versions/{ident}/fact-revisions",
    schemas.FactRevisionInput,
    review.save,
    "version",
    "document.review",
    201,
)
mutation(
    "/document-versions/{ident}/line-identities",
    schemas.Reason,
    review.issue_line,
    "version",
    "document.review",
    201,
)
mutation(
    "/document-fact-revisions/{ident}/submissions",
    schemas.Submission,
    review.submit,
    "fact",
    "document.review.submit",
)
mutation(
    "/documents/{ident}/mapping-revisions",
    schemas.MappingInput,
    mapping.save,
    "document",
    "document.map",
    201,
)
mutation(
    "/document-versions/{ident}/assessment-runs",
    schemas.AssessmentInput,
    jobs.assessment,
    "version",
    "document.check",
    202,
)
mutation(
    "/document-findings/{ident}/annotations",
    schemas.AnnotationInput,
    checks.annotate,
    "finding",
    "document.check",
    201,
)
mutation(
    "/document-versions/{ident}/verification-checks",
    schemas.VerificationInput,
    verification.request_check,
    "version",
    "document.verify.request",
    202,
)
mutation(
    "/document-versions/{ident}/manual-attestations",
    schemas.ManualAttestation,
    verification.manual,
    "version",
    "document.manual_attestation.record",
    201,
)
mutation(
    "/organizations/{ident}/verification-connections",
    schemas.ConnectionInput,
    verification.create_connection,
    "organization",
    "document.provider.configure",
    201,
)


@router.get("/trades/{ident}/documents")
def documents(
    ident: UUID,
    request: Request,
    type: str | None = None,
    status: str | None = None,
    cursor: UUID | None = None,
    db: Session = Depends(get_db),
):
    return views.register(db, context(request, db), ident, type, status, cursor)


@router.get("/documents/{ident}")
def document(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row, _ = access.document(db, ctx, ident)
    body = views.document_view(db, ctx, row)
    body["mapping_summary"] = views.mapped_summary(db, ctx, row)
    return body


@router.get("/document-versions/{ident}")
def version(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row, doc, _ = access.version(db, ctx, ident)
    selected = db.scalar(
        select(FactRevision)
        .where(FactRevision.document_version_id == row.id)
        .order_by(FactRevision.revision_number.desc())
    )
    if not access.full_capture(db, ctx, doc):
        selected = (
            db.get(FactRevision, doc.effective_fact_revision_id)
            if doc.effective_fact_revision_id
            else None
        )
    return {
        **result(row, doc),
        "selected_fact_revision_id": selected.id if selected else None,
        "is_current_source": row.id == doc.current_version_id,
        "document": views.document_view(db, ctx, doc, row),
    }


@router.get("/document-processing-jobs/{ident}")
def job(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return jobs.job_view(db, context(request, db), exists(db, Job, ident))


@router.get("/document-versions/{ident}/pages")
def pages(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row, doc, _ = access.version(db, ctx, ident)
    access.capture(db, ctx, doc)
    jobs.clean_assets(db, row)
    return {
        "items": [
            {
                **result(p),
                "source_attachment_id": db.get(
                    Artifact, p.page_image_artifact_id
                ).source_attachment_id,
            }
            for p in db.scalars(
                select(Page)
                .where(Page.document_version_id == row.id)
                .order_by(Page.page_number, Page.created_at)
            )
        ]
    }


@router.get("/document-artifacts/{ident}")
def artifact(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row = exists(db, Artifact, ident)
    version, doc, _ = access.version(db, ctx, row.document_version_id)
    access.capture(db, ctx, doc)
    jobs.clean_assets(db, version)
    if row.artifact_type not in {"PAGE_IMAGE", "THUMBNAIL"}:
        fail(
            "FORBIDDEN",
            "Raw extraction/provider artifacts are not available through preview routes.",
            status=403,
        )
    return result(row)


@router.get("/document-pages/{ident}/preview")
def preview(ident: UUID, request: Request, db: Session = Depends(get_db)):
    import os

    ctx = context(request, db)
    page = exists(db, Page, ident)
    version, doc, _ = access.version(db, ctx, page.document_version_id)
    access.capture(db, ctx, doc)
    jobs.clean_assets(db, version)
    db.commit()
    url = os.getenv("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8013").rstrip("/")
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                f"{url}/document-desk/artifacts/{page.page_image_artifact_id}/authorization",
                headers={**service_headers(), "X-Organization-Id": ctx.org_id},
            )
        if response.status_code != 200:
            fail("PREVIEW_UNAVAILABLE", "Safe preview authorization is unavailable.", status=503)
        return response.json()
    except httpx.HTTPError:
        fail("PREVIEW_UNAVAILABLE", "Safe preview storage is unavailable.", status=503)


@router.get("/document-versions/{ident}/extraction-runs")
def extraction_runs(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row, doc, _ = access.version(db, ctx, ident)
    access.capture(db, ctx, doc)
    return {
        "items": [
            result(r, doc)
            for r in db.scalars(
                select(Extraction)
                .where(Extraction.document_version_id == row.id)
                .order_by(Extraction.created_at)
            )
        ]
    }


@router.get("/document-extraction-runs/{ident}/observations")
def observations(ident: UUID, request: Request, db: Session = Depends(get_db)):
    row = exists(db, Extraction, ident)
    ctx = context(request, db)
    _, doc, _ = access.version(db, ctx, row.document_version_id)
    access.capture(db, ctx, doc)
    return {
        "items": [
            result(o, doc)
            for o in db.scalars(select(Observation).where(Observation.extraction_run_id == row.id))
        ]
    }


@router.get("/document-fact-revisions/{ident}")
def facts(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return review.fact_view(db, context(request, db), exists(db, FactRevision, ident))


@router.get("/documents/{ident}/mapping-suggestions")
def suggestions(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return mapping.suggestions(db, context(request, db), ident)


@router.get("/documents/{ident}/mappings")
def mappings(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return mapping.history(db, context(request, db), ident)


@router.get("/document-assessment-runs/{ident}")
def assessment(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return checks.assessment_view(db, context(request, db), exists(db, Assessment, ident))


@router.get("/trades/{ident}/document-assessment-summary")
def summary(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return views.summary(db, context(request, db), ident)


@router.get("/verification-capabilities")
def capabilities(request: Request, db: Session = Depends(get_db)):
    return verification.capabilities(db, context(request, db))


@router.get("/document-verification-checks/{ident}")
def check(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return verification.check_view(db, context(request, db), exists(db, VerificationCheck, ident))


@router.get("/document-versions/{ident}/manual-attestations")
def manual_attestations(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row, doc, _ = access.version(db, ctx, ident)
    return {
        "items": [
            {**result(a, doc), "method": "MANUAL_REPORTED"}
            for a in db.scalars(
                select(ManualAttestation)
                .where(ManualAttestation.document_version_id == row.id)
                .order_by(ManualAttestation.created_at)
            )
        ]
    }


@router.get("/organizations/{ident}/verification-connections")
def connections(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    if str(ident) != ctx.org_id:
        fail("FORBIDDEN", "Select your organisation context.", status=403)
    access.require(db, ctx.user, ctx.org_id, "organization.read")
    return {
        "items": [
            result(c)
            for c in db.scalars(select(Connection).where(Connection.organization_id == ctx.org_id))
        ]
    }


@router.get("/document-versions/{ident}/evidence-manifest")
def manifest(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return views.manifest(db, context(request, db), ident)


@router.get("/consignments/{ident}/document-context")
def document_context(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return views.context_view(db, context(request, db), ident)


@router.get("/consignments/{ident}/document-operational-projections")
def operational_projections(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    access.consignment(db, ctx, ident)
    return {"items": views.operational_projections(db, ctx, ident)}


@router.get("/documents/{ident}/operational-projection")
def projection(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    doc, _ = access.document(db, ctx, ident, projection=True)
    fact = (
        db.get(FactRevision, doc.effective_fact_revision_id)
        if doc.effective_fact_revision_id
        else None
    )
    fields = flatten(fact.canonical_document_json) if fact else {}
    grants = db.scalars(
        select(AccessGrant).where(
            AccessGrant.document_version_id == doc.current_version_id,
            AccessGrant.grantee_organization_id == ctx.org_id,
            AccessGrant.access_type == "OPERATIONAL_PROJECTION",
            AccessGrant.revoked_at.is_(None),
        )
    )
    paths = {
        p
        for g in grants
        if access.active_assignment(
            db,
            ctx,
            db.get(
                Assignment,
                g.assignment_id,
            ),
        )
        for p in g.allowed_field_paths_json
    }
    return {
        "document_id": doc.id,
        "document_type": doc.document_type,
        "execution_mode": doc.execution_mode,
        "fields": {k: v for k, v in fields.items() if k in paths & access.OPERATIONAL_PATHS},
        "printed_fields_are_unverified": True,
        "dispatch_readiness": "NOT_ASSESSED",
    }


class LeaseInput(Schema):
    job_id: UUID
    attempt_id: UUID
    lease_token: str = Field(min_length=20, max_length=100)


@internal.post("/input")
def worker_input(payload: LeaseInput, db: Session = Depends(get_db)):
    job, attempt = jobs.leased(
        db, str(payload.job_id), str(payload.attempt_id), payload.lease_token
    )
    ctx = jobs.job_context(db, job)
    version, doc, _ = access.version(
        db,
        ctx,
        job.document_version_id,
        "document.verify.request" if job.stage == "VERIFY" else "document.process",
    )
    jobs.clean_assets(db, version)
    assets = []
    for a in db.scalars(select(Asset).where(Asset.document_version_id == version.id)):
        attachment = db.get(Attachment, a.attachment_id)
        assets.append(
            {
                **result(a),
                "content_type": attachment.content_type,
                "original_name": attachment.original_name,
            }
        )
    body = {
        "version_id": version.id,
        "document_id": doc.id,
        "trade_id": doc.trade_id,
        "execution_mode": doc.execution_mode,
        "document_type": doc.document_type,
        "attempt_id": attempt.id,
        "stage": job.stage,
        "request": job.request_json,
        "configuration": jobs.configuration(),
        "assets": assets,
    }
    if job.stage == "VERIFY":
        check = db.scalar(select(VerificationCheck).where(VerificationCheck.job_id == job.id))
        fact = db.get(FactRevision, check.fact_revision_id) if check.fact_revision_id else None
        body.update(
            verification_input_hash=check.input_hash,
            target_value=flatten(fact.canonical_document_json).get(check.target_field_path)
            if fact
            else None,
            trusted_keys=[
                {**result(k), "public_key_reference": k.public_key_reference}
                for k in db.scalars(select(TrustedKey))
            ],
            signed_artifact=result(db.get(Artifact, check.signed_payload_artifact_id))
            if check.signed_payload_artifact_id
            else None,
            connection=None,
        )
        if check.signed_payload_artifact_id:
            signed = db.get(Artifact, check.signed_payload_artifact_id)
            number = signed.transformation_metadata_json.get("page_number")
            candidates = (
                list(
                    db.scalars(
                        select(Page).where(
                            Page.document_version_id == version.id, Page.page_number == number
                        )
                    )
                )
                if number
                else []
            )
            body["signed_page_artifact"] = next(
                (
                    result(a)
                    for page in candidates
                    if (a := db.get(Artifact, page.page_image_artifact_id)).source_attachment_id
                    == signed.source_attachment_id
                ),
                None,
            )
        if check.connection_id:
            connection = db.get(Connection, check.connection_id)
            if connection.organization_id != ctx.org_id:
                fail("NOT_FOUND", "Verification connection not found.", status=404)
            body["connection"] = {
                **result(connection),
                "secret_reference": connection.secret_reference,
            }
    db.commit()
    return body


@router.get("/document-field-catalog")
def field_catalog(request: Request, db: Session = Depends(get_db)):
    from datetime import date, datetime
    from decimal import Decimal
    from typing import get_args

    ctx = context(request, db)
    access.require(db, ctx.user, ctx.org_id, "organization.read")
    fields = []

    def walk(model, prefix=""):
        for name, info in model.model_fields.items():
            if name in {"schema_version", "document_line_ref"}:
                continue
            path = f"{prefix}.{name}" if prefix else name
            annotation = info.annotation
            if name == "lines" and not prefix:
                walk(schemas.GoodsLine, "lines.*")
                continue
            candidates = get_args(annotation) or (annotation,)
            child = next((c for c in candidates if hasattr(c, "model_fields")), None)
            if child:
                walk(child, path)
            else:
                kind = (
                    "INTEGER"
                    if int in candidates
                    else "BOOLEAN"
                    if bool in candidates
                    else "DECIMAL"
                    if Decimal in candidates
                    else "DATE"
                    if date in candidates
                    else "TIMESTAMP"
                    if datetime in candidates
                    else "STRING"
                )
                fields.append({"path": path, "value_type": kind, "nullable": True})

    walk(schemas.CanonicalDocument)
    return {
        "schema_version": "PH3_CANONICAL_V1",
        "fields": fields,
        "json_schema": schemas.CanonicalDocument.model_json_schema(),
    }
