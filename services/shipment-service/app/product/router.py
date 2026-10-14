"""Product integration routes with revocation-safe commands and uncached private reads."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.operations.access import exists, fail
from app.trades.access import require
from app.trades.models import Participant, Trade
from app.trades.transactions import context, mutate

from . import access, assurance, bundles, demo, rehearsal, replay, tasks, workspace
from . import schemas as s
from .models import Comparison, ReplayRequest

router = APIRouter(tags=["Product integration - Phase 7"])


def private(value):
    return JSONResponse(
        value,
        headers={
            "Cache-Control": "private, no-store",
            "Vary": "Cookie, Authorization, X-Organization-Id",
        },
    )


@router.get("/me/workspaces")
@router.get("/me/action-inbox")
def inbox(request: Request, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "consignment.read")
    from app.operations.models import Assignment, Consignment

    party_trades = select(Participant.trade_id).where(Participant.organization_id == ctx.org_id)
    carrier_trades = (
        select(Consignment.trade_id)
        .join(Assignment, Assignment.consignment_id == Consignment.id)
        .where(Assignment.carrier_organization_id == ctx.org_id)
    )
    records = []
    for row in db.scalars(
        select(Trade)
        .where(Trade.id.in_(party_trades.union(carrier_trades)))
        .order_by(Trade.created_at.desc())
        .limit(limit)
    ):
        try:
            value = workspace.read(db, ctx, row.id)
            records.append(
                {
                    "trade_id": row.id,
                    "trade_reference": row.reference,
                    "execution_mode": row.execution_mode,
                    "tasks": value["tasks"],
                    "permitted_module_codes": value["permitted_module_codes"],
                }
            )
        except Exception as exc:
            from app.trades.errors import TradeError

            if not isinstance(exc, TradeError) or exc.status not in {403, 404}:
                raise
    return private({"workspaces": records, "limit": limit, "pagination": "BOUNDED_MOST_RECENT"})


@router.get("/trades/{ident}/workspace")
@router.get("/trades/{ident}/workspace/tasks")
@router.get("/trades/{ident}/journey-evidence-manifest")
def journey(
    ident: UUID,
    request: Request,
    selected_workspace_role: str | None = Query(None, max_length=80),
    module: s.Module | None = None,
    consignment_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    from app.trades.context_locks import registry_lock

    registry_lock(db)
    ctx = context(request, db)
    access.workspace(db, ctx, str(ident), True)
    value = workspace.read(
        db,
        ctx,
        str(ident),
        selected_workspace_role,
        module,
        str(consignment_id) if consignment_id else None,
    )
    # Validate the public projection without adding absent private dimensions.
    s.WorkspaceView.model_validate(value)
    head = workspace.refresh_head(db, exists(db, Trade, str(ident)))
    value["projection_version"] = head.projection_version
    db.commit()
    return private(value)


def command(path, schema, service, authorize, status=200):
    def endpoint(
        request: Request, payload: schema, ident: UUID | None = None, db: Session = Depends(get_db)
    ):
        response = mutate(
            request,
            db,
            lambda session, ctx, value: service(session, ctx, str(ident) if ident else None, value),
            payload,
            authorize=lambda session, ctx: authorize(
                session, ctx, str(ident) if ident else None, payload
            ),
            status=status,
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response

    endpoint.__name__ = "product_" + path.replace("/", "_").replace("{ident}", "record")
    router.add_api_route(path, endpoint, methods=["POST"], status_code=status)


command(
    "/trades/{ident}/workspace-task-states",
    s.TaskCommand,
    tasks.change,
    lambda db, ctx, ident, p: access.workspace(db, ctx, ident, True),
)
command(
    "/evidence/replay-requests",
    s.ReplayInput,
    replay.request,
    lambda db, ctx, ident, p: replay.subject(db, ctx, p.subject_type, str(p.subject_id)),
    202,
)
command(
    "/evidence/comparison-jobs",
    s.ComparisonInput,
    replay.comparison,
    lambda db, ctx, ident, p: [
        replay.subject(db, ctx, ref.subject_type, str(ref.subject_id))
        for ref in (p.left_subject_reference, p.right_subject_reference)
    ],
    201,
)
command(
    "/evidence/bundle-jobs",
    s.BundleInput,
    bundles.request,
    lambda db, ctx, ident, p: replay.subject(
        db, ctx, p.subject_type, str(p.subject_id), "evidence.bundle.request"
    ),
    202,
)


@router.get("/evidence/replay-results/{ident}")
def replay_result(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return private(replay.read(db, context(request, db), str(ident)))


@router.get("/evidence/comparisons/{ident}")
def comparison_result(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row = exists(db, Comparison, str(ident))
    if row.created_by_user_id != ctx.user.id:
        fail("NOT_FOUND", "Comparison not found.", status=404)
    projections = []
    for ref in (row.left_request_id, row.right_request_id):
        requested = exists(db, ReplayRequest, ref)
        if requested.requested_by_organisation_id != ctx.org_id:
            fail("NOT_FOUND", "Comparison not found.", status=404)
        subject, _ = replay.subject(db, ctx, requested.subject_type, requested.subject_id)
        projections.append(replay.projection(db, ctx, requested.subject_type, subject))
    return private(
        {
            "id": row.id,
            "explanation_items": replay.diff(*projections),
            "current_readiness": "NOT_ASSESSED_BY_REPLAY",
        }
    )


@router.get("/evidence/bundles/{ident}")
@router.get("/evidence/bundles/{ident}/download")
def bundle(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return private(
        bundles.read(db, context(request, db), str(ident), request.url.path.endswith("/download"))
    )


@router.get("/readiness/context")
def readiness_context(request: Request, db: Session = Depends(get_db)):
    value = assurance.context(db, context(request, db))
    db.commit()
    return private(value)


@router.get("/readiness/runs/{ident}")
@router.get("/readiness/runs/{ident}/evidence-manifest")
def readiness_result(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return private(assurance.read(db, context(request, db), str(ident)))


@router.get("/deployments/{ident}/health")
def health(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return private(assurance.health(db, context(request, db), str(ident)))


def privileged(permission):
    def authorize(db, ctx, ident, payload):
        if permission.startswith(("readiness.", "deployment.", "pilot.scope.")):
            return assurance.control(db, ctx, permission)
        return require(db, ctx.user, ctx.org_id, permission)

    return authorize


command("/readiness/runs", s.RunInput, assurance.enqueue, privileged("readiness.run"), 202)
command(
    "/readiness/runs/{ident}/manual-review-records",
    s.ManualInput,
    assurance.manual,
    lambda db, ctx, ident, p: assurance.read(db, ctx, ident),
    201,
)
command(
    "/readiness/runs/{ident}/qualification-decisions",
    s.QualificationInput,
    assurance.qualify,
    lambda db, ctx, ident, p: (
        require(db, ctx.user, ctx.org_id, "readiness.review"),
        assurance.read(db, ctx, ident),
    ),
    201,
)
command(
    "/pilot-scope-revisions", s.ScopeInput, assurance.scope, privileged("pilot.scope.prepare"), 201
)
command(
    "/pilot-scope-revisions/{ident}/review-approvals",
    s.ScopeReview,
    assurance.review_scope,
    privileged("pilot.scope.review"),
    201,
)
command(
    "/deployments/{ident}/pauses", s.PauseInput, assurance.pause, privileged("deployment.pause")
)
command(
    "/deployments/{ident}/activations",
    s.ActivationInput,
    assurance.activate,
    privileged("deployment.activate"),
)
command(
    "/deployments/{ident}/restore-rehearsal-jobs",
    s.RestoreInput,
    rehearsal.run,
    privileged("deployment.restore.rehearse"),
    201,
)


@router.get("/demo/scenarios")
def scenarios(request: Request, db: Session = Depends(get_db)):
    return private(demo.catalog(db, context(request, db)))


@router.get("/demo/workspaces/{ident}")
def demo_workspace(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return private(demo.read(db, context(request, db), str(ident)))


@router.get("/demo/runs/{ident}")
def demo_run(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return private(demo.run_view(db, context(request, db), str(ident)))


command("/demo/workspaces", s.DemoCreate, demo.create, privileged("demo.workspace.create"), 201)
command(
    "/demo/workspaces/{ident}/clock-advances",
    s.ClockAdvance,
    demo.advance,
    lambda db, ctx, ident, p: demo.access(db, ctx, ident, "demo.clock.advance"),
)
command(
    "/demo/workspaces/{ident}/reset-successors",
    s.DemoCreate,
    demo.reset,
    lambda db, ctx, ident, p: demo.access(db, ctx, ident, "demo.workspace.create"),
    201,
)
command(
    "/demo/workspaces/{ident}/runs",
    s.DemoRunInput,
    demo.start,
    lambda db, ctx, ident, p: demo.access(db, ctx, ident, "demo.run"),
    201,
)
command(
    "/demo/runs/{ident}/step-executions",
    s.DemoStep,
    demo.step,
    lambda db, ctx, ident, p: demo.run_access(db, ctx, ident),
)
command(
    "/demo/runs/{ident}/cancellations",
    s.Reason,
    demo.cancel,
    lambda db, ctx, ident, p: demo.run_access(db, ctx, ident),
)
command(
    "/demo/runs/{ident}/measurements",
    s.MeasurementInput,
    demo.measure,
    lambda db, ctx, ident, p: demo.run_access(db, ctx, ident),
    201,
)
