"""Existing authentication, grants, idempotency and transaction boundaries apply."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.ledger import view
from app.database import get_db
from app.operations.access import consignment, exists, fail
from app.trades.access import require
from app.trades.transactions import context, mutate

from . import events, governance, service, sources
from . import schemas as s
from .models import (
    Assessment,
    Connection,
    EventRevision,
    GovernanceAction,
    Incident,
    Mapping,
    Policy,
    RecoveryCase,
)

router = APIRouter(tags=["Corridor intelligence - Phase 6"])


def authorize(db, ctx, ident, resource, permission):
    if resource not in {"consignment", "case"}:
        require(db, ctx.user, ctx.org_id, permission)
    if resource == "connection":
        sources.owned(db, ctx, ident, permission)
    elif resource == "incident":
        head = exists(db, Incident, ident)
        if head.owner_organisation_id != ctx.org_id:
            fail("NOT_FOUND", "Incident not found.", status=404)
    elif resource == "event":
        row = exists(db, EventRevision, ident)
        head = exists(db, Incident, row.incident_id)
        if head.owner_organisation_id != ctx.org_id:
            fail("NOT_FOUND", "Event not found.", status=404)
    elif resource in {"consignment", "case"}:
        cn_id = exists(db, RecoveryCase, ident).consignment_id if resource == "case" else ident
        consignment(db, ctx, cn_id, permission, lock=True)


def command(path, schema, operation, resource, permission, status=200, collection=False):
    def execute(request, payload, db, ident=None):
        return mutate(
            request,
            db,
            lambda session, ctx, value: operation(
                session, ctx, str(ident) if ident else None, value
            ),
            payload,
            status=status,
            authorize=lambda session, ctx: authorize(
                session, ctx, str(ident) if ident else None, resource, permission
            ),
        )

    if collection:

        def endpoint(request: Request, payload: schema, db: Session = Depends(get_db)):
            return execute(request, payload, db)
    else:

        def endpoint(ident: UUID, request: Request, payload: schema, db: Session = Depends(get_db)):
            return execute(request, payload, db, ident)

    endpoint.__name__ = "corridor_" + path.replace("/", "_").replace("{ident}", "record")
    router.add_api_route(path, endpoint, methods=["POST"], status_code=status)


command(
    "/corridor/source-connections",
    s.ConnectionInput,
    sources.create,
    "registry",
    "regulation.source.register",
    201,
    True,
)
command(
    "/corridor/source-connections/{ident}/status",
    s.ConnectionStatus,
    sources.status,
    "connection",
    "regulation.source.register",
)
command(
    "/corridor/manual-source-items",
    s.SourceInput,
    sources.manual,
    "registry",
    "regulation.source.register",
    201,
    True,
)
command(
    "/corridor/incidents",
    s.IncidentInput,
    events.incident,
    "registry",
    "regulation.source.register",
    201,
    True,
)
command(
    "/corridor/incidents/{ident}/event-revisions",
    s.EventInput,
    events.create,
    "incident",
    "regulation.source.register",
    201,
)
command(
    "/corridor/event-revisions/{ident}/reviews",
    s.Review,
    events.review,
    "event",
    "regulation.pack.review",
)
command(
    "/corridor/event-revisions/{ident}/publications",
    s.Exact,
    events.publish,
    "event",
    "regulation.pack.publish",
)
command(
    "/corridor/event-revisions/{ident}/withdrawals",
    s.Reason,
    events.withdraw,
    "event",
    "regulation.pack.publish",
)
command(
    "/corridor/event-revisions/{ident}/reopening-evidence",
    s.Reopening,
    events.reopening,
    "event",
    "regulation.pack.review",
)
command(
    "/corridor/effect-policy-revisions",
    s.PolicyInput,
    governance.create,
    "registry",
    "regulation.pack.prepare",
    201,
    True,
)
command(
    "/corridor/mapping-revisions",
    s.MappingInput,
    governance.mapping,
    "registry",
    "regulation.pack.prepare",
    201,
    True,
)
command(
    "/corridor/effect-policy-revisions/{ident}/review-approvals",
    s.Review,
    governance.decide,
    "registry",
    "regulation.pack.review",
)
command(
    "/corridor/effect-policy-revisions/{ident}/publications",
    s.Exact,
    lambda db, ctx, ident, payload: governance.decide(db, ctx, ident, payload, publish=True),
    "registry",
    "regulation.pack.publish",
)
command(
    "/corridor/mapping-revisions/{ident}/review-approvals",
    s.Review,
    lambda db, ctx, ident, payload: governance.decide(db, ctx, ident, payload, Mapping),
    "registry",
    "regulation.pack.review",
)
command(
    "/corridor/mapping-revisions/{ident}/publications",
    s.Exact,
    lambda db, ctx, ident, payload: governance.decide(db, ctx, ident, payload, Mapping, True),
    "registry",
    "regulation.pack.publish",
)
command(
    "/consignments/{ident}/corridor-reassessments",
    s.Reassessment,
    service.reassess,
    "consignment",
    "tradetwin.run",
    201,
)
command(
    "/consignments/{ident}/recovery-cases",
    s.CaseInput,
    service.create_case,
    "consignment",
    "tradetwin.plan.apply",
    201,
)
command(
    "/recovery-cases/{ident}/driver-responses",
    s.DriverInput,
    service.driver_response,
    "case",
    "shipment.event.record",
    201,
)


@router.get("/consignments/{ident}/dynamic-tradetwin-context")
def dynamic(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return service.dynamic_context(db, context(request, db), str(ident))


@router.get("/corridor-impact-assessments/{ident}")
def assessment(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return service.assessment_view(db, context(request, db), exists(db, Assessment, ident))


@router.get("/recovery-cases/{ident}")
def recovery(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return service.case_view(db, context(request, db), exists(db, RecoveryCase, ident))


@router.get("/corridor/registry")
def registry(request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "organization.read")
    result = {
        "source_connections": [
            sources.public(c)
            for c in db.scalars(
                select(Connection)
                .where(Connection.owner_organisation_id == ctx.org_id)
                .order_by(Connection.created_at.desc())
            )
        ]
    }
    for name, model, column in [
        ("policies", Policy, GovernanceAction.policy_revision_id),
        ("mappings", Mapping, GovernanceAction.mapping_revision_id),
    ]:
        result[name] = [
            {
                **view(row),
                "active": governance.active(db, row),
                "actions": [
                    view(a)
                    for a in db.scalars(
                        select(GovernanceAction)
                        .where(column == row.id)
                        .order_by(GovernanceAction.sequence_number)
                    )
                ],
            }
            for row in db.scalars(select(model).order_by(model.created_at.desc()))
        ]
    result["incidents"] = [
        {
            **view(row),
            "etag": f'"{row.row_version}"',
            "revisions": [
                {
                    **view(e),
                    "state": events.state(db, e),
                    "actions": [view(a) for a in events.history(db, e)],
                }
                for e in db.scalars(
                    select(EventRevision)
                    .where(EventRevision.incident_id == row.id)
                    .order_by(EventRevision.revision_number.desc())
                )
            ],
        }
        for row in db.scalars(
            select(Incident)
            .where(Incident.owner_organisation_id == ctx.org_id)
            .order_by(Incident.created_at.desc())
        )
    ]
    return result
