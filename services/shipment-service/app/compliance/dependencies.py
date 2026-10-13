"""Private dependency fingerprints. These records are never an API projection."""

from sqlalchemy import select

from app.document_desk.models import (
    Artifact,
    Connection,
    ManualAttestation,
    TrustedKey,
    VerificationCheck,
    VerificationResult,
)
from app.operations.models import Attachment
from app.trades.access import aware
from app.trades.terms import digest

from .models import ManualEvidence, ManualReview


def verification_state(db, binding):
    refs = [
        binding.binding_json["movement_document"],
        *binding.binding_json.get("supporting_documents", []),
    ]
    versions = {r["document_version_id"]: r["reviewed_fact_revision_id"] for r in refs}
    selected = set(binding.binding_json.get("verification_result_ids", []))
    results = list(
        db.scalars(
            select(VerificationResult)
            .join(VerificationCheck)
            .where(VerificationCheck.document_version_id.in_(versions))
            .order_by(VerificationResult.id)
        )
    )
    records, key_ids = [], set()
    for result in results:
        check = db.get(VerificationCheck, result.verification_check_id)
        if check.fact_revision_id != versions[check.document_version_id]:
            continue
        data = result.result_json
        if data.get("trusted_key_id"):
            key_ids.add(data["trusted_key_id"])
        connection = db.get(Connection, check.connection_id) if check.connection_id else None
        artifacts = [check.signed_payload_artifact_id, data.get("signed_qr_artifact_id")]
        records.append(
            {
                "id": result.id,
                "hash": digest(data),
                "selected": result.id in selected,
                "input_hash": check.input_hash,
                "connection": {
                    "id": connection.id,
                    "version": connection.row_version,
                    "status": connection.status,
                    "environment": connection.provider_environment,
                    "checks": connection.allowed_check_types_json,
                }
                if connection
                else None,
                "artifacts": [
                    {"id": a.id, "hash": a.sha256, "kind": a.artifact_type}
                    for i in artifacts
                    if i and (a := db.get(Artifact, i))
                ],
            }
        )
    keys = [
        {
            "id": k.id,
            "fingerprint": k.key_fingerprint,
            "status": k.status,
            "policy": k.registry_policy_version,
            "environment": k.provider_environment,
            "purpose": k.key_purpose,
            "algorithm": k.algorithm,
            "effective_from": aware(k.effective_from).isoformat() if k.effective_from else None,
            "effective_until": aware(k.effective_until).isoformat() if k.effective_until else None,
        }
        for i in sorted(key_ids)
        if (k := db.get(TrustedKey, i))
    ]
    return records, keys


def manual_state(db, binding):
    values = []
    for ident in sorted(binding.binding_json.get("manual_attestation_ids", [])):
        report = db.get(ManualAttestation, ident)
        structured = db.scalar(select(ManualEvidence).where(ManualEvidence.attestation_id == ident))
        reviews = list(
            db.scalars(
                select(ManualReview)
                .where(ManualReview.attestation_id == ident)
                .order_by(ManualReview.created_at, ManualReview.id)
            )
        )
        values.append(
            {
                "id": ident,
                "source_version": report.document_version_id,
                "fact_revision": report.fact_revision_id,
                "structured_hash": digest(structured.observed_fields_json) if structured else None,
                "review_ids": [r.id for r in reviews],
                "assets": [
                    {"id": a.id, "hash": a.sha256, "security_state": a.security_state}
                    for i in (structured.supporting_attachment_ids if structured else [])
                    if (a := db.get(Attachment, i))
                ],
            }
        )
    return values
