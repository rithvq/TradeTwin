import os

from sqlalchemy import select

from app.operations.models import (
    Assignment,
    Consignment,
    ConsignmentItem,
    Payment,
    PaymentAllocation,
    PaymentDecision,
    ReceiptHead,
)
from app.trades.models import Organization, Revision, Trade
from app.trades.terms import digest

from .models import Asset, Document, TrustedKey, Version

CHECK_PACK = "PH3_DOCUMENT_DATA_CHECKS_V1"


def input_context(db, doc, request=None):
    request = request or {}
    trade = db.get(Trade, doc.trade_id)
    revision = db.get(Revision, trade.accepted_revision_id) if trade.accepted_revision_id else None
    cn_ids = request.get("consignment_ids") or []
    query = select(Consignment).where(Consignment.trade_id == trade.id)
    if cn_ids:
        query = query.where(Consignment.id.in_(cn_ids))
    consignments = list(db.scalars(query.order_by(Consignment.id)))
    ids = [cn.id for cn in consignments]
    assignments = list(
        db.scalars(
            select(Assignment).where(Assignment.consignment_id.in_(ids)).order_by(Assignment.id)
        )
    )
    receipts = list(
        db.scalars(
            select(ReceiptHead).where(ReceiptHead.consignment_id.in_(ids)).order_by(ReceiptHead.id)
        )
    )
    decisions = list(
        db.scalars(
            select(PaymentDecision)
            .join(Payment)
            .where(Payment.trade_id == trade.id)
            .order_by(PaymentDecision.id)
        )
    )
    allocations = list(
        db.scalars(
            select(PaymentAllocation)
            .join(Payment)
            .where(Payment.trade_id == trade.id)
            .order_by(PaymentAllocation.id)
        )
    )
    related = []
    for ident in request.get("related_document_version_ids", []):
        version = db.get(Version, str(ident))
        other = db.get(Document, version.document_id)
        related.append(
            {
                "version_id": version.id,
                "current_version_id": other.current_version_id,
                "fact_revision_id": other.effective_fact_revision_id
                or other.latest_draft_fact_revision_id,
            }
        )
    version = db.get(Version, doc.current_version_id)
    return {
        "source_manifest_hash": version.source_manifest_hash,
        "document_version_id": version.id,
        "fact_revision_id": doc.latest_draft_fact_revision_id
        if request.get("fact_selector") == "DRAFT"
        else doc.effective_fact_revision_id or doc.latest_draft_fact_revision_id,
        "mapping_revision_id": doc.current_mapping_revision_id,
        "accepted_revision_id": trade.accepted_revision_id,
        "accepted_terms_hash": revision.terms_hash if revision else None,
        "consignments": [
            {
                "id": cn.id,
                "row_version": cn.row_version,
                "source_accepted_revision_id": cn.source_accepted_revision_id,
                "assignment_id": cn.active_assignment_id,
                "plan_hash": digest(cn.plan_json),
                "plan_snapshot": cn.plan_json,
                "items_snapshot": [
                    {"id": i.id, "allocated_quantity": str(i.allocated_quantity), "uqc": i.uqc}
                    for i in db.scalars(
                        select(ConsignmentItem)
                        .where(ConsignmentItem.consignment_id == cn.id)
                        .order_by(ConsignmentItem.id)
                    )
                ],
            }
            for cn in consignments
        ],
        "assignments": [
            {
                "id": a.id,
                "row_version": a.row_version,
                "status": a.status,
                "vehicle_snapshot": a.vehicle_snapshot,
                "carrier_legal_name": db.get(Organization, a.carrier_organization_id).legal_name,
            }
            for a in assignments
        ],
        "receipt_heads": [
            {"id": r.id, "row_version": r.row_version, "receipt_id": r.effective_receipt_id}
            for r in receipts
        ],
        "payment_decisions": [p.id for p in decisions],
        "payment_allocations": [a.id for a in allocations],
        "reported_payment_ids": list(
            db.scalars(select(Payment.id).where(Payment.trade_id == trade.id).order_by(Payment.id))
        ),
        "assets": [
            {"id": a.attachment_id, "hash": a.asset_sha256}
            for a in db.scalars(
                select(Asset).where(Asset.document_version_id == version.id).order_by(Asset.id)
            )
        ],
        "related_documents": related,
        "check_pack_version": CHECK_PACK,
        "arithmetic_tolerance_minor": str(
            max(0, int(os.getenv("DOCUMENT_ARITHMETIC_TOLERANCE_MINOR", "1")))
        ),
        "trust_policy_hash": digest(
            [
                {
                    "id": k.id,
                    "fingerprint": k.key_fingerprint,
                    "policy": k.registry_policy_version,
                    "status": k.status,
                }
                for k in db.scalars(select(TrustedKey).order_by(TrustedKey.id))
            ]
        ),
        "request_scope": {
            **{k: request.get(k, []) for k in ("consignment_ids", "related_document_version_ids")},
            "fact_selector": request.get("fact_selector", "EFFECTIVE"),
        },
    }


def freshness(db, doc, saved, ctx=None):
    current = input_context(db, doc, saved.get("request_scope", {}))
    observed = saved.get("assessment_observation")
    basis = {k: v for k, v in saved.items() if k != "assessment_observation"}
    if digest(current) != digest(basis):
        return "STALE"
    if observed:
        from datetime import datetime

        from app.trades.access import aware
        from app.trades.models import now

        if aware(datetime.fromisoformat(observed["fresh_until"])) <= now():
            return "STALE"
        if ctx:
            from .checks import duplicate_candidates

            if digest(observed["duplicate_candidates"]) != digest(
                duplicate_candidates(db, ctx, doc)
            ):
                return "STALE"
    return "CURRENT"


def mapping_freshness(db, doc, saved):
    current = input_context(db, doc)

    def basis(value):
        return {
            **{
                k: value.get(k)
                for k in (
                    "source_manifest_hash",
                    "document_version_id",
                    "fact_revision_id",
                    "mapping_revision_id",
                    "accepted_revision_id",
                    "accepted_terms_hash",
                )
            },
            "target_items": [
                i for cn in value.get("consignments", []) for i in cn.get("items_snapshot", [])
            ],
        }

    return "CURRENT" if digest(basis(current)) == digest(basis(saved)) else "STALE"
