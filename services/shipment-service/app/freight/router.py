"""Typed Phase 5 routes with shared revocation-safe idempotency and transactions."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.operations.access import exists, fail, lock_trade
from app.operations.models import Vehicle
from app.trades.access import require
from app.trades.transactions import context, mutate

from . import commitments, offers, routing, runs, views
from . import schemas as s
from .access import planning, rfq_access
from .models import (
    RFQ,
    Assumptions,
    Cancellation,
    Commitment,
    Invitation,
    Provider,
    Quote,
    QuoteHead,
    Run,
)

router = APIRouter(tags=["Freight planning - Phase 5"])


def authorize(db, ctx, ident, resource, permission, payload):
    if resource == "consignment":
        return planning(db, ctx, ident, permission, True)
    if resource == "vehicle":
        vehicle = exists(db, Vehicle, ident)
        if vehicle.carrier_organization_id != ctx.org_id:
            fail("NOT_FOUND", "Vehicle not found.", status=404)
        return require(db, ctx.user, ctx.org_id, permission)
    if resource == "dataset":
        return require(db, ctx.user, ctx.org_id, permission)
    if resource == "rfq":
        return rfq_access(db, ctx, ident, permission, True)
    if resource == "quote":
        row = exists(db, Quote, ident)
        head = exists(db, QuoteHead, row.quote_head_id)
        _, trade, _, carrier = rfq_access(db, ctx, head.rfq_id, lock=True)
        if not carrier or head.carrier_organisation_id != ctx.org_id:
            fail("NOT_FOUND", "Offer not found.", status=404)
        return require(db, ctx.user, ctx.org_id, permission, trade.id)
    if resource == "selection":
        return commitments.exact(db, ctx, ident, permission)
    if resource == "cancellation":
        row = exists(db, Cancellation, ident)
        committed = exists(db, Commitment, row.commitment_id)
        trade = lock_trade(db, committed.trade_id)
        roles = {
            "PAYER": (
                committed.commitment_json["freight_payer_organisation_id"],
                "freight.commit.approve",
            ),
            "COORDINATOR": (
                committed.commitment_json["coordinating_organisation_id"],
                "tradetwin.plan.apply",
            ),
            "CARRIER": (
                committed.commitment_json["carrier_organisation_id"],
                "freight.offer.accept",
            ),
        }
        org, code = roles[payload.decision_role]
        if ctx.org_id != org:
            fail("FORBIDDEN", "Only the responsible cancellation party can decide.", status=403)
        return require(db, ctx.user, ctx.org_id, code, trade.id)
    model = {"run": Run, "assumptions": Assumptions, "commitment": Commitment}[resource]
    row = exists(db, model, ident)
    return planning(db, ctx, row.consignment_id, permission, True)


def command(path, schema, service, resource, permission, status=200):
    def endpoint(ident: UUID, request: Request, payload: schema, db: Session = Depends(get_db)):
        return mutate(
            request,
            db,
            lambda session, ctx, value: service(session, ctx, str(ident), value),
            payload,
            status=status,
            authorize=lambda session, ctx: authorize(
                session, ctx, str(ident), resource, permission, payload
            ),
        )

    endpoint.__name__ = "freight_" + path.replace("/", "_").replace("{ident}", "record")
    router.add_api_route(path, endpoint, methods=["POST"], status_code=status)


command(
    "/consignments/{ident}/routing-location-revisions",
    s.LocationInput,
    routing.location,
    "consignment",
    "tradetwin.plan.prepare",
    201,
)
command(
    "/vehicles/{ident}/routing-profile-revisions",
    s.ProfileInput,
    routing.profile,
    "vehicle",
    "vehicle.manage",
    201,
)
command(
    "/consignments/{ident}/route-generation-jobs",
    s.GenerateInput,
    routing.generate,
    "consignment",
    "tradetwin.plan.prepare",
    202,
)
command(
    "/consignments/{ident}/freight-rfqs",
    s.RFQInput,
    offers.create_rfq,
    "consignment",
    "freight.rfq.prepare",
    201,
)
command(
    "/freight-rfqs/{ident}/publications",
    s.RequestHashCommand,
    offers.publish,
    "rfq",
    "freight.rfq.publish",
)
command("/freight-rfqs/{ident}/closures", s.Reason, offers.close, "rfq", "freight.rfq.publish")
command(
    "/freight-rfqs/{ident}/invitations",
    s.InvitationInput,
    offers.invite,
    "rfq",
    "freight.rfq.publish",
)
command(
    "/freight-rfqs/{ident}/quote-revisions",
    s.QuoteInput,
    offers.create_quote,
    "rfq",
    "freight.rfq.invited.read",
    201,
)
command(
    "/freight-quote-revisions/{ident}/submissions",
    s.QuoteHashCommand,
    lambda db, ctx, ident, payload: offers.quote_event(db, ctx, ident, payload, "SUBMITTED"),
    "quote",
    "freight.quote.submit",
)
command(
    "/freight-quote-revisions/{ident}/withdrawals",
    s.QuoteHashCommand,
    lambda db, ctx, ident, payload: offers.quote_event(db, ctx, ident, payload, "WITHDRAWN"),
    "quote",
    "freight.quote.submit",
)
command(
    "/consignments/{ident}/tradetwin-cost-assumption-revisions",
    s.AssumptionsInput,
    offers.assumptions,
    "consignment",
    "tradetwin.cost_assumptions.prepare",
    201,
)
command(
    "/tradetwin-cost-assumption-revisions/{ident}/reviews",
    s.ReviewInput,
    offers.assumption_review,
    "assumptions",
    "tradetwin.cost_assumptions.review",
)
command(
    "/consignments/{ident}/tradetwin-runs",
    s.RunInput,
    runs.request,
    "consignment",
    "tradetwin.run",
    202,
)
command(
    "/tradetwin-runs/{ident}/scenario-runs",
    s.ScenarioRun,
    runs.scenario_run,
    "run",
    "tradetwin.run",
    202,
)
command("/tradetwin-runs/{ident}/cancellations", s.Reason, runs.cancel, "run", "tradetwin.run")
command(
    "/consignments/{ident}/tradetwin-selections",
    s.SelectionInput,
    commitments.propose,
    "consignment",
    "tradetwin.selection.prepare",
    201,
)
command(
    "/tradetwin-selections/{ident}/payer-decisions",
    s.SelectionDecision,
    lambda db, ctx, ident, payload: commitments.approve(db, ctx, ident, payload, "PAYER"),
    "selection",
    "PAYER",
)
command(
    "/tradetwin-selections/{ident}/coordinator-decisions",
    s.SelectionDecision,
    lambda db, ctx, ident, payload: commitments.approve(db, ctx, ident, payload, "COORDINATOR"),
    "selection",
    "COORDINATOR",
)
command(
    "/tradetwin-selections/{ident}/carrier-decisions",
    s.CarrierDecision,
    commitments.accept,
    "selection",
    "CARRIER",
)
command(
    "/tradetwin-selections/{ident}/cancellations",
    s.Reason,
    commitments.cancel_selection,
    "selection",
    None,
)
command(
    "/freight-commitments/{ident}/cancellation-proposals",
    s.CancellationInput,
    commitments.propose_cancellation,
    "commitment",
    "freight.commit.approve",
    201,
)
command(
    "/freight-cancellation-proposals/{ident}/decisions",
    s.CancellationDecisionInput,
    commitments.cancel_commitment,
    "cancellation",
    None,
)
for action, path, permission in [
    ("REVIEW_APPROVED", "review-approvals", "routing.dataset.review"),
    ("PUBLISHED", "publications", "routing.dataset.publish"),
    ("SUSPENDED", "suspensions", "routing.dataset.publish"),
]:

    def dataset_service(db, ctx, ident, payload, action=action):
        return routing.dataset_event(db, ctx, ident, payload, action)

    command(
        "/routing/dataset-revisions/{ident}/" + path,
        s.HashCommand,
        dataset_service,
        "dataset",
        permission,
    )


@router.post("/routing/dataset-revisions", status_code=201)
def dataset(request: Request, payload: s.DatasetInput, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        routing.dataset,
        payload,
        status=201,
        authorize=lambda session, ctx: require(
            session, ctx.user, ctx.org_id, "routing.dataset.prepare"
        ),
    )


@router.get("/routing/dataset-revisions")
def dataset_records(request: Request, db: Session = Depends(get_db)):
    from app.operations.ledger import view

    from .models import Dataset, DatasetEvent

    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "routing.dataset.read")
    return {
        "items": [
            {
                **view(d),
                "status": (
                    e.event_type
                    if (
                        e := db.scalar(
                            select(DatasetEvent)
                            .where(DatasetEvent.dataset_revision_id == d.id)
                            .order_by(DatasetEvent.created_at.desc())
                        )
                    )
                    else "DRAFT"
                ),
            }
            for d in db.scalars(select(Dataset).order_by(Dataset.created_at.desc()).limit(50))
        ]
    }


@router.get("/consignments/{ident}/tradetwin-context")
def current_context(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return views.context_view(db, context(request, db), str(ident))


@router.get("/consignments/{ident}/route-templates")
def templates(ident: UUID, request: Request, db: Session = Depends(get_db)):
    from app.operations.ledger import view

    from .models import Template

    ctx = context(request, db)
    _, cn = planning(db, ctx, ident)
    return {
        "items": [
            view(t) for t in db.scalars(select(Template).where(Template.consignment_id == cn.id))
        ]
    }


@router.get("/freight-rfqs")
def invited(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "freight.rfq.invited.read")
    ids = list(
        db.scalars(
            select(RFQ.id)
            .join(Invitation)
            .where(
                Invitation.carrier_organisation_id == ctx.org_id,
                Invitation.revoked_at.is_(None),
                RFQ.lifecycle_projection != "DRAFT",
            )
            .order_by(RFQ.created_at.desc())
            .limit(50)
        )
    )
    return {"items": [views.rfq_view(db, ctx, i) for i in ids]}


def read_route(path, service):
    def endpoint(ident: UUID, request: Request, db: Session = Depends(get_db)):
        return service(db, context(request, db), str(ident))

    endpoint.__name__ = "read_freight_" + path.replace("/", "_").replace("{ident}", "record")
    router.add_api_route(path, endpoint, methods=["GET"])


read_route("/freight-rfqs/{ident}", views.rfq_view)
read_route("/freight-quotes/{ident}", views.quote_history)
read_route("/freight-quote-revisions/{ident}", views.quote_view)
read_route("/tradetwin-runs/{ident}", views.run_view)
read_route("/tradetwin-selections/{ident}", views.selection_view)
read_route("/freight-commitments/{ident}", views.commitment_view)
read_route("/consignments/{ident}/route-plan", views.route_plan)
read_route("/tradetwin-runs/{ident}/evidence-manifest", views.evidence)
read_route("/tradetwin-runs/{ident}/graph", views.graph)
read_route(
    "/freight-commitments/{ident}/evidence-manifest",
    lambda db, ctx, ident: views.evidence(db, ctx, ident, "commitment"),
)


@router.get("/tradetwin-candidates/{ident}")
def candidate(ident: UUID, request: Request, db: Session = Depends(get_db)):
    from .models import Candidate

    row = exists(db, Candidate, ident)
    data = views.run_view(db, context(request, db), row.run_id)
    return next(c for c in data["candidates"] if c["candidate_id"] == row.id)


@router.get("/routing/provider-capabilities")
def providers(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "routing.provider.read")
    return {
        "items": [
            {
                "id": p.id,
                "provider_code": p.provider_code,
                "status": p.status,
                "capabilities": p.capabilities_json,
                "licensing": p.licensing_json,
            }
            for p in db.scalars(
                select(Provider).where(
                    (Provider.organisation_id == ctx.org_id) | Provider.organisation_id.is_(None)
                )
            )
        ],
        "default_status": "NOT_CONFIGURED",
        "synthetic_production_fallback": False,
    }


@router.get("/routing/own-fleet")
def own_fleet(request: Request, db: Session = Depends(get_db)):
    from app.operations.ledger import view
    from app.trades.models import Grant, Membership, User, now

    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "freight.quote.prepare")
    vehicles = list(
        db.scalars(
            select(Vehicle).where(
                Vehicle.carrier_organization_id == ctx.org_id, Vehicle.active.is_(True)
            )
        )
    )
    drivers = list(
        db.scalars(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .join(Grant, Grant.membership_id == Membership.id)
            .where(
                Membership.organization_id == ctx.org_id,
                Membership.status == "ACTIVE",
                User.active.is_(True),
                Grant.capability == "DRIVER",
                Grant.permission_code == "shipment.event.record",
                Grant.revoked_at.is_(None),
                (Grant.expires_at.is_(None) | (Grant.expires_at > now())),
            )
        )
    )
    return {
        "vehicles": [view(v) for v in vehicles],
        "drivers": [
            {"id": d.id, "display_name": d.display_name}
            for d in {d.id: d for d in drivers}.values()
        ],
        "transport_evidence": owned_evidence(db, ctx),
    }


def owned_evidence(db, ctx):
    from app.compliance.models import TransportEvidence

    return [
        {
            "id": e.id,
            "consignment_id": e.consignment_id,
            "subject_id": e.subject_id,
            "evidence_type": e.evidence_type,
        }
        for e in db.scalars(
            select(TransportEvidence)
            .where(TransportEvidence.owner_organisation_id == ctx.org_id)
            .order_by(TransportEvidence.created_at.desc())
            .limit(100)
        )
    ]


@router.get("/route-generation-jobs/{ident}")
def generation(ident: UUID, request: Request, db: Session = Depends(get_db)):
    from .models import Generation

    row = exists(db, Generation, ident)
    ctx = context(request, db)
    planning(db, ctx, row.consignment_id)
    return {"job_id": row.id, "job_state": row.job_state, "result": row.result_json}


@router.get("/consignments/{ident}/tradetwin-cost-assumptions")
def cost_assumptions(ident: UUID, request: Request, db: Session = Depends(get_db)):
    from .access import payer
    from .models import AssumptionReview

    ctx = context(request, db)
    trade, cn = planning(db, ctx, ident)
    if ctx.org_id != payer(db, trade)[0]:
        fail("NOT_FOUND", "Private payer assumptions not found.", status=404)
    require(db, ctx.user, ctx.org_id, "freight.price.read", trade.id)
    from app.operations.ledger import view

    records = list(
        db.scalars(
            select(Assumptions)
            .where(Assumptions.consignment_id == cn.id)
            .order_by(Assumptions.revision_number.desc())
        )
    )
    return {
        "items": [
            {
                **view(a),
                "review_decision": (
                    r.decision
                    if (
                        r := db.scalar(
                            select(AssumptionReview)
                            .where(AssumptionReview.assumption_revision_id == a.id)
                            .order_by(AssumptionReview.created_at.desc())
                        )
                    )
                    else "UNREVIEWED"
                ),
            }
            for a in records
        ]
    }


@router.get("/freight-commitments/{ident}/cancellation-proposals")
def cancellation_desk(ident: UUID, request: Request, db: Session = Depends(get_db)):
    from app.operations.ledger import view

    from .models import CancellationDecision

    ctx = context(request, db)
    committed = exists(db, Commitment, ident)
    data = committed.commitment_json
    role = (
        "PAYER"
        if ctx.org_id == data["freight_payer_organisation_id"]
        else "CARRIER"
        if ctx.org_id == data["carrier_organisation_id"]
        else "COORDINATOR"
        if ctx.org_id == data["coordinating_organisation_id"]
        else None
    )
    if role is None:
        fail("NOT_FOUND", "Cancellation record not found.", status=404)
    require(
        db,
        ctx.user,
        ctx.org_id,
        {
            "PAYER": "freight.commit.approve",
            "CARRIER": "freight.offer.accept",
            "COORDINATOR": "tradetwin.plan.apply",
        }[role],
        committed.trade_id,
    )
    records = []
    for row in db.scalars(select(Cancellation).where(Cancellation.commitment_id == committed.id)):
        value = dict(row.cancellation_json)
        if role == "COORDINATOR":
            for key in ["proposed_fee_position", "proposed_fee_minor", "proposed_fee_note"]:
                value.pop(key, None)
        records.append(
            {
                "id": row.id,
                "etag": view(row)["etag"],
                "proposal_hash": row.proposal_hash,
                "status": row.status,
                "cancellation": value,
                "already_decided": bool(
                    db.scalar(
                        select(CancellationDecision.id).where(
                            CancellationDecision.cancellation_proposal_id == row.id,
                            CancellationDecision.decision_role == role,
                        )
                    )
                ),
            }
        )
    return {
        "commitment_hash": committed.content_hash,
        "role": role,
        "can_propose": role == "PAYER",
        "items": records,
    }
