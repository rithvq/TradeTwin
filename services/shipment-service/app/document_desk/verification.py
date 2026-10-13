import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select

from app.operations import attachments
from app.operations.access import exists, fail
from app.trades.access import aware, require
from app.trades.models import now
from app.trades.terms import digest

from . import access, jobs
from .context import CHECK_PACK, input_context
from .ledger import field_path, record, result
from .models import (
    Artifact,
    Connection,
    FactRevision,
    ManualAttestation,
    TrustedKey,
    VerificationCheck,
    VerificationResult,
)


def request_check(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.verify.request", True)
    fact = exists(db, FactRevision, payload.fact_revision_id) if payload.fact_revision_id else None
    if fact and fact.document_version_id != version.id:
        fail("OBSERVATION_SOURCE_MISMATCH", "Verification facts belong to another source.")
    if payload.target_field_path and not field_path(payload.target_field_path):
        fail("VALIDATION_ERROR", "Unknown verification field path.", status=422)
    identifiers = {
        "IRN_LIVE_STATUS": {"header.irn"},
        "EWB_AUTHORITY_LOOKUP": {"eway_bill.eway_bill_number"},
        "GSTIN_AUTHORITY_LOOKUP": {
            f"parties.{role}.gstin" for role in ("supplier", "recipient", "bill_from", "bill_to")
        },
        "GSTIN_FORMAT": {
            f"parties.{role}.gstin" for role in ("supplier", "recipient", "bill_from", "bill_to")
        },
    }
    if (
        payload.check_type in identifiers
        and payload.target_field_path not in identifiers[payload.check_type]
    ):
        fail(
            "VALIDATION_ERROR",
            "Select the appropriate identifier field for this check.",
            status=422,
        )
    if payload.connection_id:
        connection = exists(db, Connection, payload.connection_id)
        if connection.organization_id != ctx.org_id:
            fail("NOT_FOUND", "Verification connection not found.", status=404)
    if payload.signed_payload_artifact_id:
        artifact = exists(db, Artifact, payload.signed_payload_artifact_id)
        if (
            artifact.document_version_id != version.id
            or artifact.artifact_type != "DECODED_SIGNED_PAYLOAD"
        ):
            fail(
                "OBSERVATION_SOURCE_MISMATCH", "Signed payload belongs to another source or format."
            )
    artifact_id = (
        str(payload.signed_payload_artifact_id) if payload.signed_payload_artifact_id else None
    )
    if not artifact_id and payload.check_type in {"IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE"}:
        candidates = db.scalars(
            select(Artifact)
            .where(
                Artifact.document_version_id == version.id,
                Artifact.artifact_type == "DECODED_SIGNED_PAYLOAD",
            )
            .order_by(Artifact.created_at.desc())
        )
        wanted = (
            {"QR", "SignedQRCode"}
            if payload.check_type == "IRP_QR_SIGNATURE"
            else {"SignedInvoice"}
        )
        artifact_id = next(
            (
                a.id
                for a in candidates
                if a.transformation_metadata_json.get("token_kind") in wanted
            ),
            None,
        )
    values = payload.model_dump(mode="json")
    values["signed_payload_artifact_id"] = artifact_id
    values["input_context"] = input_context(
        db,
        doc,
        {
            "fact_selector": "DRAFT"
            if fact
            and fact.id == doc.latest_draft_fact_revision_id
            and fact.id != doc.effective_fact_revision_id
            else "EFFECTIVE"
        },
    )
    values["input_context"]["document_version_id"] = version.id
    values["input_context"]["source_manifest_hash"] = version.source_manifest_hash
    if fact:
        values["input_context"]["fact_revision_id"] = fact.id
    row = jobs.enqueue(db, ctx, version, doc, "VERIFY", values, True)
    check = VerificationCheck(
        document_version_id=version.id,
        fact_revision_id=fact.id if fact else None,
        job_id=row.id,
        check_type=payload.check_type,
        target_field_path=payload.target_field_path,
        signed_payload_artifact_id=artifact_id,
        connection_id=str(payload.connection_id) if payload.connection_id else None,
        input_hash=digest(
            {
                "manifest": version.source_manifest_hash,
                "fact": fact.content_hash if fact else None,
                "request": values,
            }
        ),
        request_configuration_json=values,
        requested_by_user_id=ctx.user.id,
    )
    db.add(check)
    record(
        db,
        ctx,
        "DOCUMENT_VERIFICATION_REQUESTED",
        doc,
        version,
        {"check_type": payload.check_type, "job_id": row.id},
    )
    return {
        "check_id": check.id,
        "job_id": row.id,
        "status": "QUEUED",
        "execution_mode": doc.execution_mode,
        "status_url": f"/api/v1/document-processing-jobs/{row.id}",
    }


def check_view(db, ctx, row):
    _, doc, _ = access.version(db, ctx, row.document_version_id)
    from .context import freshness

    values = []
    for observation in db.scalars(
        select(VerificationResult).where(VerificationResult.verification_check_id == row.id)
    ):
        data = observation.result_json
        inputs = row.request_configuration_json.get("input_context")
        current = freshness(db, doc, inputs) if inputs else "STALE"
        if data.get("fresh_until") and aware(datetime.fromisoformat(data["fresh_until"])) <= now():
            current = "STALE"
        body = result(observation, doc)
        if not access.full_capture(db, ctx, doc):
            body["result_json"] = {**data, "normalised_result": {}, "response_artifact_id": None}
        values.append({**body, "freshness": current})
    body = result(row, doc)
    body.pop("request_configuration_json", None)
    return {**body, "results": values, "dispatch_readiness": "NOT_ASSESSED"}


def manual(db, ctx, ident, payload):
    version, doc, trade = access.version(db, ctx, ident, "document.manual_attestation.record", True)
    url = urlsplit(payload.portal_source_url)
    allowed = {
        "gst.gov.in",
        "services.gst.gov.in",
        "einvoice.gst.gov.in",
        "ewaybillgst.gov.in",
        "ewaybill.nic.in",
    }
    if url.scheme != "https" or url.hostname not in allowed or url.username or url.password:
        fail(
            "VALIDATION_ERROR",
            "Use an approved official portal source; no URL is fetched.",
            status=422,
        )
    if payload.observed_at > now() + timedelta(minutes=5):
        fail("VALIDATION_ERROR", "Portal observations cannot be future dated.", status=422)
    row = ManualAttestation(
        document_version_id=version.id,
        fact_revision_id=doc.effective_fact_revision_id,
        **payload.model_dump(exclude={"evidence_attachment_ids", "observed_fields"}),
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(row)
    attachments.link(db, ctx, trade, None, row, payload.evidence_attachment_ids)
    if payload.observed_fields:
        from app.compliance.models import ManualEvidence

        db.add(
            ManualEvidence(
                attestation_id=row.id,
                observed_fields_json=payload.observed_fields,
                supporting_attachment_ids=[str(i) for i in payload.evidence_attachment_ids],
                created_by_user_id=ctx.user.id,
            )
        )
    record(
        db,
        ctx,
        "DOCUMENT_PORTAL_ATTESTATION_RECORDED",
        doc,
        version,
        {"attestation_id": row.id, "method": "MANUAL_REPORTED"},
    )
    return {
        **result(row, doc),
        "method": "MANUAL_REPORTED",
        "label": "Portal observation reported by reviewer",
    }


def create_connection(db, ctx, ident, payload):
    if str(ident) != ctx.org_id:
        fail("FORBIDDEN", "Use your organisation context.", status=403)
    require(db, ctx.user, ctx.org_id, "document.provider.configure")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", payload.authorised_secret_binding):
        fail("VALIDATION_ERROR", "Select a pre-authorised server secret binding name.", status=422)
    raw_binding = os.getenv(f"DOCUMENT_PROVIDER_BINDING_{payload.authorised_secret_binding}")
    if not raw_binding:
        fail(
            "PROVIDER_BINDING_NOT_CONFIGURED",
            "Configure this binding through server secret management first.",
        )
    try:
        binding = json.loads(raw_binding)
    except (ValueError, TypeError):
        fail("PROVIDER_BINDING_NOT_CONFIGURED", "Server binding configuration is invalid.")
    if (
        binding.get("organization_id") != ctx.org_id
        or binding.get("provider_environment") != payload.provider_environment
    ):
        fail(
            "FORBIDDEN",
            "Server binding is not authorised for this organisation and environment.",
            status=403,
        )
    row = Connection(
        organization_id=ctx.org_id,
        adapter_name=payload.adapter_name,
        adapter_version="1",
        provider_environment=payload.provider_environment,
        requester_identifier=payload.requester_identifier,
        secret_reference=payload.authorised_secret_binding,
        allowed_check_types_json=payload.allowed_check_types,
        created_by=ctx.user.id,
    )
    db.add(row)
    from app.trades.ledger import audit

    audit(
        db,
        ctx,
        "DOCUMENT_PROVIDER_CONNECTION_CONFIGURED",
        row,
        summary={"adapter": row.adapter_name, "environment": row.provider_environment},
    )
    return result(row)


def capabilities(db, ctx):
    require(db, ctx.user, ctx.org_id, "organization.read")
    keys = [result(k) for k in db.scalars(select(TrustedKey))]
    return {
        "check_pack": {
            "id": CHECK_PACK,
            "version": "1",
            "kind": "DATA_RECONCILIATION_ONLY",
            "status": "PUBLISHED",
        },
        "canonical_schema": "PH3_CANONICAL_V1",
        "checks": [
            {
                "check_type": kind,
                "adapter": "PH3_LOCAL_CHECKS"
                if kind
                in {"GSTIN_FORMAT", "IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE", "PDF_SIGNATURE"}
                else "AUTHORISED_READ_ONLY_V1",
                "availability": "UNSUPPORTED"
                if kind == "PDF_SIGNATURE"
                else "AVAILABLE"
                if kind == "GSTIN_FORMAT"
                else "KEY_REQUIRED"
                if kind in {"IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE"}
                else "CONNECTION_REQUIRED",
            }
            for kind in (
                "GSTIN_FORMAT",
                "GSTIN_AUTHORITY_LOOKUP",
                "IRP_QR_SIGNATURE",
                "IRP_JSON_SIGNATURE",
                "IRN_LIVE_STATUS",
                "EWB_AUTHORITY_LOOKUP",
                "PDF_SIGNATURE",
            )
        ],
        "trusted_keys": keys,
        "supported_profiles": [
            "SIMPLE_DECLARED_TOTALS",
            "EINVOICE_CAPTURE_V1",
            "COMPACT_JWS_RS256",
        ],
        "environments": ["SIMULATION", "SANDBOX", "LIVE"],
        "limitations": [
            "No GST applicability, IRN/EWB generation, filing, bank verification, "
            "or production dispatch authorisation.",
            "PDF signature trust/revocation checking is unsupported.",
        ],
    }
