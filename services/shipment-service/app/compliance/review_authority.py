"""Required review permissions are live dependencies, not indefinitely reusable assertions."""

from sqlalchemy import select

from app.operations.access import exists, fail

from . import context
from .models import (
    Binding,
    Fact,
    FactReview,
    Manifest,
    ManualReview,
    TransportEvidence,
    TransportReview,
    Turnover,
    TurnoverReview,
)


def release_preparers(db, evaluation):
    actors = {evaluation.created_by_user_id}
    binding = (
        db.get(Binding, evaluation.binding_revision_id) if evaluation.binding_revision_id else None
    )
    if binding:
        actors.add(binding.created_by_user_id)
        for model, ident in (
            (Fact, binding.fact_revision_id),
            (Manifest, binding.loading_manifest_revision_id),
        ):
            if ident and (row := db.get(model, ident)):
                actors.add(row.created_by_user_id)
    return actors


def windows(db, evaluation, trade, cn):
    from .dispatch import live_grant

    binding = exists(db, Binding, evaluation.binding_revision_id)
    owner = context.inherited(db, trade, cn)["seller_organisation_id"]
    reviews = []
    fact = db.scalar(
        select(FactReview)
        .where(FactReview.fact_revision_id == binding.fact_revision_id)
        .order_by(FactReview.created_at.desc(), FactReview.id.desc())
    )
    reviews.append((fact, owner, "compliance.facts.review"))
    if binding.turnover_declaration_id:
        declaration = exists(db, Turnover, binding.turnover_declaration_id)
        latest = db.scalar(
            select(TurnoverReview)
            .where(TurnoverReview.declaration_id == declaration.id)
            .order_by(TurnoverReview.created_at.desc(), TurnoverReview.id.desc())
        )
        reviews.append((latest, declaration.seller_organisation_id, "turnover.review"))
    for ident in binding.binding_json.get("transport_evidence_revision_ids", []):
        exists(db, TransportEvidence, ident)
        latest = db.scalar(
            select(TransportReview)
            .where(TransportReview.evidence_revision_id == ident)
            .order_by(TransportReview.created_at.desc(), TransportReview.id.desc())
        )
        reviews.append(
            (
                latest,
                latest.reviewer_organisation_id if latest else None,
                "transport.evidence.review",
            )
        )
    for ident in binding.binding_json.get("manual_attestation_ids", []):
        latest = db.scalar(
            select(ManualReview)
            .where(ManualReview.attestation_id == ident)
            .order_by(ManualReview.created_at.desc(), ManualReview.id.desc())
        )
        if latest:
            reviews.append(
                (latest, latest.reviewer_organisation_id, "document.manual_observation.review")
            )
    deadlines = []
    for review, organisation, permission in reviews:
        if review is None or review.decision != "APPROVE_DECLARATION":
            fail(
                "COMPLIANCE_NOT_READY",
                "A required current independent declaration review is missing or returned.",
            )
        end = live_grant(db, review.created_by_user_id, organisation, trade.id, permission)
        if end:
            deadlines.append(end)
    return deadlines
