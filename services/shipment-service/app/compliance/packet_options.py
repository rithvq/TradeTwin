"""Curated packet choices, not a financial-document access grant."""

from sqlalchemy import select

from app.document_desk.models import Asset, Document, VerificationResult
from app.trades.access import require
from app.trades.errors import TradeError

from .models import Binding, ReleaseReview


def sources(db, ctx, evaluation, trade):
    try:
        require(db, ctx.user, ctx.org_id, "dispatch.packet.prepare", trade.id)
    except TradeError:
        return []
    approved = db.scalar(
        select(ReleaseReview)
        .where(ReleaseReview.evaluation_id == evaluation.id)
        .order_by(ReleaseReview.created_at.desc(), ReleaseReview.id.desc())
    )
    if not approved or approved.decision != "APPROVE_RELEASE":
        return []
    binding = db.get(Binding, evaluation.binding_revision_id)
    if not binding:
        return []
    options = []
    for ref in [
        binding.binding_json["movement_document"],
        *binding.binding_json.get("supporting_documents", []),
    ]:
        doc = db.get(Document, ref["document_id"])
        if doc.document_type not in {"TAX_INVOICE", "EWAY_BILL_COPY"}:
            continue
        options.append(
            {
                "document_type": doc.document_type,
                "document_version_id": ref["document_version_id"],
                "assets": [
                    {"attachment_id": a.attachment_id}
                    for a in db.scalars(
                        select(Asset).where(Asset.document_version_id == ref["document_version_id"])
                    )
                ],
                "signed_qr_artifact_ids": [
                    data["signed_qr_artifact_id"]
                    for i in binding.binding_json.get("verification_result_ids", [])
                    if (data := db.get(VerificationResult, i).result_json).get(
                        "signed_qr_artifact_id"
                    )
                    and doc.document_type == "TAX_INVOICE"
                ],
            }
        )
    return options
