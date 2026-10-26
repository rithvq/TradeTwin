"""Thin Phase 4 commands; all writes use the existing authenticated transaction service."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.operations.access import exists
from app.trades.access import require
from app.trades.transactions import context as actor_context
from app.trades.transactions import mutate

from . import (
    bindings,
    context,
    dispatch,
    evaluations,
    facts,
    governance,
    handoff,
    packet_files,
    recipient,
    reviews,
    turnover,
)
from .models import (
    Authorization,
    Evaluation,
    Fact,
    Hold,
    Packet,
    ReviewCase,
    TransportEvidence,
    Turnover,
)
from .schemas_dashboard import DispatchDashboardView, DispatchJourneyView
from .schemas_dispatch import (
    Acknowledge,
    AuthorizationInput,
    CaseActionInput,
    HoldInput,
    HoldRelease,
    PacketPrepare,
    Reason,
    ReleaseDecision,
)
from .schemas_facts import (
    Action,
    BindingPrepare,
    DeclarationReview,
    EvaluationInput,
    FactPrepare,
    IdentityInput,
    ManifestPrepare,
    Mode,
    RecipientInput,
    TransportInput,
    TurnoverInput,
)
from .schemas_rules import (
    ConflictInput,
    ConflictResolution,
    PackInput,
    PackReview,
    PackTestInput,
    PublishInput,
    SourceInput,
)
from .schemas_views import ComputationTraceView, ConstraintView, EvidenceManifestView, ReadinessView

router = APIRouter(tags=["Compliance and guarded dispatch - Phase 4"])


@router.get("/dispatch-dashboard", response_model=DispatchDashboardView)
def dispatch_dashboard(
    request: Request,
    response: Response,
    cursor: UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    from .dashboard import listing

    response.headers["Cache-Control"] = "private, no-store"
    return listing(db, actor_context(request, db), str(cursor) if cursor else None, limit)


@router.get("/consignments/{ident}/dispatch-journey", response_model=DispatchJourneyView)
def dispatch_journey(
    ident: UUID,
    request: Request,
    response: Response,
    action: Action = "PICKUP_CONFIRMED",
    db: Session = Depends(get_db),
):
    from .dashboard import journey

    response.headers["Cache-Control"] = "private, no-store"
    return journey(db, actor_context(request, db), str(ident), action)


def authorize(db, ctx, resource, ident, permission, seller=False):
    if resource == "manual":
        from app.document_desk.access import version
        from app.document_desk.models import ManualAttestation

        return version(
            db, ctx, exists(db, ManualAttestation, ident).document_version_id, permission, True
        )
    if resource == "consignment":
        return context.access(db, ctx, str(ident), permission, seller, True)
    if resource == "organisation":
        return turnover.private_access(db, ctx, str(ident), permission)
    if resource == "turnover":
        row = exists(db, Turnover, ident)
        return turnover.private_access(db, ctx, row.seller_organisation_id, permission)
    model = {
        "fact": Fact,
        "transport": TransportEvidence,
        "evaluation": Evaluation,
        "packet": Packet,
        "authorization": Authorization,
        "case": ReviewCase,
        "hold": Hold,
    }.get(resource)
    if model:
        row = exists(db, model, ident)
        if resource == "hold" and not row.consignment_id:
            return reviews.hold_access(db, ctx, row, permission)
        return context.access(db, ctx, row.consignment_id, permission, seller, True)
    return require(db, ctx.user, ctx.org_id, permission)


def command(path, schema, service, resource, permission, status=201, seller=False):
    def endpoint(ident: UUID, request: Request, payload: schema, db: Session = Depends(get_db)):
        capability = reviews.case_permission(payload) if resource == "case" else permission
        return mutate(
            request,
            db,
            lambda session, ctx, value: service(session, ctx, str(ident), value),
            payload,
            status=status,
            authorize=lambda session, ctx: authorize(
                session, ctx, resource, ident, capability, seller
            ),
            conflict_code="IDEMPOTENCY_CONFLICT",
        )

    endpoint.__name__ = "phase4_" + path.replace("/", "_").replace("{ident}", "record")
    router.add_api_route(path, endpoint, methods=["POST"], status_code=status)


@router.get("/consignments/{ident}/compliance-context")
def compliance_context(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return context.public_context(db, actor_context(request, db), str(ident))


@router.get("/pan-turnover-declarations/{ident}")
def private_turnover(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return turnover.read(db, actor_context(request, db), str(ident))


@router.get("/organisations/{ident}/pan-turnover-declarations")
def turnover_list(ident: UUID, request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import select

    ctx = actor_context(request, db)
    turnover.private_access(db, ctx, str(ident), "turnover.read")
    return {
        "items": [
            {
                "id": r.id,
                "content_hash": r.content_hash,
                "assessment_invoice_date": r.assessment_invoice_date,
                "prepared_by_user_id": r.created_by_user_id,
                "review_outcome": (
                    last.decision if (last := turnover.last_review(db, r.id)) else "UNREVIEWED"
                ),
            }
            for r in db.scalars(
                select(Turnover)
                .where(Turnover.seller_organisation_id == str(ident))
                .order_by(Turnover.created_at.desc(), Turnover.id.desc())
            )
        ]
    }


command(
    "/consignments/{ident}/compliance-fact-revisions",
    FactPrepare,
    facts.prepare,
    "consignment",
    "compliance.facts.prepare",
    seller=True,
)

command(
    "/consignments/{ident}/compliance-evaluations",
    EvaluationInput,
    evaluations.request,
    "consignment",
    "compliance.evaluate",
    202,
    True,
)
command(
    "/compliance-evaluations/{ident}/review-decisions",
    ReleaseDecision,
    reviews.release,
    "evaluation",
    "dispatch.release.approve",
    seller=True,
)
command(
    "/compliance-cases/{ident}/actions",
    CaseActionInput,
    reviews.case_action,
    "case",
    "compliance.case.comment",
)
command(
    "/consignments/{ident}/compliance-holds",
    HoldInput,
    reviews.hold,
    "consignment",
    "compliance.hold.create",
)
command(
    "/compliance-holds/{ident}/release-requests",
    Reason,
    reviews.release_request,
    "hold",
    "compliance.hold.release.request",
)
command(
    "/compliance-holds/{ident}/release-approvals",
    HoldRelease,
    reviews.release_approval,
    "hold",
    "compliance.hold.release.approve",
)
command(
    "/consignments/{ident}/dispatch-packets",
    PacketPrepare,
    dispatch.prepare_packet,
    "consignment",
    "dispatch.packet.prepare",
)
command(
    "/dispatch-packets/{ident}/acknowledgments",
    Acknowledge,
    dispatch.acknowledge,
    "packet",
    "dispatch.packet.acknowledge",
)
command(
    "/consignments/{ident}/dispatch-authorizations",
    AuthorizationInput,
    dispatch.issue,
    "consignment",
    "dispatch.authorisation.request",
)
command(
    "/dispatch-authorizations/{ident}/revocations",
    Reason,
    dispatch.revoke,
    "authorization",
    "dispatch.authorisation.revoke",
)
command(
    "/regulations/rule-pack-revisions/{ident}/test-runs",
    PackTestInput,
    governance.test_pack,
    "regulation",
    "regulation.pack.test",
)
command(
    "/regulations/rule-pack-revisions/{ident}/review-approvals",
    PackReview,
    governance.review_pack,
    "regulation",
    "regulation.pack.review",
)
command(
    "/regulations/rule-pack-revisions/{ident}/publications",
    PublishInput,
    governance.publish,
    "regulation",
    "regulation.pack.publish",
)
command(
    "/regulations/rule-pack-revisions/{ident}/suspensions",
    Reason,
    governance.suspend,
    "regulation",
    "regulation.pack.suspend",
)
command(
    "/regulations/source-conflicts/{ident}/resolutions",
    ConflictResolution,
    governance.resolve_conflict,
    "regulation",
    "regulation.pack.review",
)


def root_command(path, schema, service, permission):
    def endpoint(request: Request, payload: schema, db: Session = Depends(get_db)):
        return mutate(
            request,
            db,
            lambda session, ctx, value: service(session, ctx, None, value),
            payload,
            status=201,
            authorize=lambda session, ctx: require(session, ctx.user, ctx.org_id, permission),
        )

    endpoint.__name__ = "phase4_" + path.replace("/", "_")
    router.add_api_route(path, endpoint, methods=["POST"], status_code=201)


root_command("/regulations/sources", SourceInput, governance.source, "regulation.source.register")
command(
    "/manual-portal-attestations/{ident}/reviews",
    DeclarationReview,
    reviews.manual_review,
    "manual",
    "document.manual_observation.review",
)


@router.get("/dispatch-packets/{ident}/items/{item_id}/download")
def packet_download(ident: UUID, item_id: UUID, request: Request, db: Session = Depends(get_db)):
    return packet_files.download(db, actor_context(request, db), str(ident), str(item_id))


@router.get("/dispatch-packets/{ident}/items/{item_id}/storage-descriptor", include_in_schema=False)
def packet_storage(ident: UUID, item_id: UUID, request: Request, db: Session = Depends(get_db)):
    return packet_files.descriptor(db, actor_context(request, db), str(ident), str(item_id))


root_command(
    "/regulations/source-conflicts",
    ConflictInput,
    governance.create_conflict,
    "regulation.source.register",
)
root_command(
    "/regulations/rule-pack-revisions", PackInput, governance.create_pack, "regulation.pack.prepare"
)


@router.get("/compliance-evaluations/{ident}")
def evaluation(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return evaluations.read(db, actor_context(request, db), str(ident))


@router.get(
    "/compliance-evaluations/{ident}/computation-trace", response_model=ComputationTraceView
)
def computation_trace(
    ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)
):
    from .computation_trace import read

    response.headers["Cache-Control"] = "private, no-store"
    return read(db, actor_context(request, db), str(ident))


@router.get("/consignments/{ident}/compliance-evaluations")
def evaluation_history(
    ident: UUID, request: Request, cursor: UUID | None = None, db: Session = Depends(get_db)
):
    return evaluations.history(
        db, actor_context(request, db), str(ident), str(cursor) if cursor else None
    )


@router.get("/consignments/{ident}/dispatch-readiness", response_model=ReadinessView)
def dispatch_readiness(
    ident: UUID,
    request: Request,
    action: Action = "PICKUP_CONFIRMED",
    db: Session = Depends(get_db),
):
    return handoff.readiness(db, actor_context(request, db), str(ident), action)


@router.get("/consignments/{ident}/compliance-cases")
def compliance_cases(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return reviews.cases(db, actor_context(request, db), str(ident))


@router.get("/dispatch-packets/{ident}")
def dispatch_packet(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return dispatch.packet_view(db, actor_context(request, db), str(ident))


@router.get("/dispatch-authorizations/{ident}")
def authorization(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return dispatch.read(db, actor_context(request, db), str(ident))


@router.get("/regulations/supported-scope")
def supported_scope(request: Request, db: Session = Depends(get_db)):
    return governance.supported_scope(db, actor_context(request, db))


@router.get("/regulations/candidate-template")
def rule_template(
    request: Request,
    source_ids: Annotated[list[UUID], Query(min_length=1, max_length=40)],
    environment: Mode = "PRODUCTION",
    db: Session = Depends(get_db),
):
    from .models import Source
    from .templates import candidate

    ctx = actor_context(request, db)
    require(db, ctx.user, ctx.org_id, "regulation.pack.prepare")
    ids = [str(value) for value in source_ids]
    for source_id in ids:
        exists(db, Source, source_id)
    return candidate(ids, environment, "draft-" + uuid4().hex[:12]).model_dump(
        mode="json", by_alias=True
    )


@router.get(
    "/compliance-evaluations/{ident}/evidence-manifest",
    response_model=EvidenceManifestView,
    response_model_exclude_unset=True,
)
def evaluation_evidence(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return handoff.evidence(db, actor_context(request, db), str(ident))


@router.get(
    "/dispatch-authorizations/{ident}/evidence-manifest",
    response_model=EvidenceManifestView,
    response_model_exclude_unset=True,
)
def authorization_evidence(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return handoff.evidence(db, actor_context(request, db), str(ident), True)


@router.get("/consignments/{ident}/compliance-constraints", response_model=ConstraintView)
def compliance_constraints(
    ident: UUID,
    request: Request,
    action: Action = "PICKUP_CONFIRMED",
    db: Session = Depends(get_db),
):
    return handoff.constraints(db, actor_context(request, db), str(ident), action)


command(
    "/compliance-fact-revisions/{ident}/reviews",
    DeclarationReview,
    facts.review,
    "fact",
    "compliance.facts.review",
    seller=True,
)
command(
    "/consignments/{ident}/recipient-confirmations",
    RecipientInput,
    recipient.prepare,
    "consignment",
    "compliance.recipient.confirm",
)
command(
    "/organisations/{ident}/private-pan-identities",
    IdentityInput,
    turnover.identity,
    "organisation",
    "turnover.prepare",
)
command(
    "/organisations/{ident}/pan-turnover-declarations",
    TurnoverInput,
    turnover.prepare,
    "organisation",
    "turnover.prepare",
)
command(
    "/pan-turnover-declarations/{ident}/reviews",
    DeclarationReview,
    turnover.review,
    "turnover",
    "turnover.review",
)
command(
    "/consignments/{ident}/loading-manifest-revisions",
    ManifestPrepare,
    facts.manifest,
    "consignment",
    "shipment.loading_manifest.prepare",
    seller=True,
)
command(
    "/consignments/{ident}/transport-evidence-revisions",
    TransportInput,
    facts.transport,
    "consignment",
    "transport.evidence.prepare",
)
command(
    "/transport-evidence-revisions/{ident}/reviews",
    DeclarationReview,
    facts.transport_review,
    "transport",
    "transport.evidence.review",
)
command(
    "/consignments/{ident}/compliance-evidence-binding-revisions",
    BindingPrepare,
    bindings.prepare,
    "consignment",
    "compliance.evidence.link",
    seller=True,
)
