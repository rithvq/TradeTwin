"""Current-source selectors, filtered through the document desk's existing ACL."""

from sqlalchemy import select

from app.document_desk import access
from app.document_desk.models import (
    Asset,
    Document,
    ManualAttestation,
    VerificationCheck,
    VerificationResult,
)
from app.operations.models import Attachment
from app.trades.access import aware
from app.trades.errors import TradeError

from .models import ManualReview, PrivateSource


def documents(db, ctx, trade_id, private_basis=False):
    values = []
    for document in db.scalars(
        select(Document)
        .where(Document.trade_id == trade_id, Document.lifecycle_status == "ACTIVE")
        .order_by(Document.id)
    ):
        try:
            access.document(db, ctx, document.id)
        except TradeError:
            continue
        if not document.effective_fact_revision_id:
            continue
        private = db.scalar(
            select(PrivateSource.id).where(PrivateSource.document_id == document.id)
        )
        if private and not private_basis:
            continue
        if private_basis and (
            document.visibility != "OWNER_ONLY"
            or document.owner_organization_id != ctx.org_id
            or document.document_type == "DRIVER_LICENCE"
        ):
            continue
        refs = {
            "document_id": document.id,
            "document_version_id": document.current_version_id,
            "reviewed_fact_revision_id": document.effective_fact_revision_id,
            "mapping_revision_id": document.current_mapping_revision_id,
            "canonical_document_id": document.canonical_document_id or document.id,
        }
        checks = list(
            db.scalars(
                select(VerificationCheck).where(
                    VerificationCheck.fact_revision_id == document.effective_fact_revision_id
                )
            )
        )
        observations = [
            {
                "id": result.id,
                "check_type": check.check_type,
                "method": result.result_json.get("method"),
                "checked_at": result.result_json.get("checked_at"),
                "fresh_until": result.result_json.get("fresh_until"),
                "environment": result.result_json.get("provider_environment"),
                "signed_qr_artifact_id": result.result_json.get("signed_qr_artifact_id"),
            }
            for check in checks
            for result in db.scalars(
                select(VerificationResult).where(
                    VerificationResult.verification_check_id == check.id
                )
            )
        ]
        reports = [
            {
                "id": r.id,
                "check_type": r.check_type,
                "observed_at": aware(r.observed_at).isoformat(),
                "reported_by_user_id": r.actor_user_id,
                "review_outcome": (
                    last.decision
                    if (
                        last := db.scalar(
                            select(ManualReview)
                            .where(ManualReview.attestation_id == r.id)
                            .order_by(ManualReview.created_at.desc(), ManualReview.id.desc())
                        )
                    )
                    else "UNREVIEWED"
                ),
            }
            for r in db.scalars(
                select(ManualAttestation).where(
                    ManualAttestation.fact_revision_id == document.effective_fact_revision_id
                )
            )
        ]
        values.append(
            {
                "id": document.id,
                "label": document.label,
                "document_type": document.document_type,
                "reference": refs,
                "assets": [
                    {
                        "attachment_id": a.attachment_id,
                        "content_type": db.get(Attachment, a.attachment_id).content_type,
                    }
                    for a in db.scalars(
                        select(Asset).where(
                            Asset.document_version_id == document.current_version_id
                        )
                    )
                ],
                "verification_results": observations,
                "manual_attestations": reports,
            }
        )
    return values
