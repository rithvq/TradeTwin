"""Thin typed endpoints; mutations share Phase 1 identity, idempotency and transactions."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.trades.access import grants, membership, require
from app.trades.models import Audit, Membership, Trade, User
from app.trades.schemas import Schema
from app.trades.transactions import context, mutate

from . import (
    allocation,
    attachments,
    disputes,
    movement,
    payments,
    receiving,
    schedules,
    transport,
    views,
)
from .access import consignment, exists, fail, lock_trade, party
from .ledger import view
from .models import (
    Assignment,
    Attachment,
    Consignment,
    Dispute,
    Inspection,
    Payment,
    PaymentAllocation,
    Receipt,
    ReceiptLine,
    Schedule,
    Vehicle,
)
from .schemas import (
    AllocationReversal,
    AssignmentDecision,
    AssignmentProposal,
    AttachmentCompletion,
    AttachmentUploadInput,
    CarrierProfileInput,
    Comment,
    ConsignmentPatch,
    ConsignmentPlan,
    DisputeInput,
    InspectionBatch,
    Notes,
    PaymentAllocationBatch,
    PaymentInput,
    PaymentScheduleInput,
    Reason,
    ReceiptCorrection,
    ReceiptInput,
    ResolutionDecision,
    ResolutionProposal,
    ScheduleApproval,
    ShipmentEventInput,
    VehicleInput,
    VehiclePatch,
    VoidDecision,
)

router = APIRouter(tags=["Trade operations - Phase 2"])


def authorize_resource(db, ctx, resource, ident, permission, side=None):
    if resource == "trade":
        return party(db, ctx, ident, permission, side, True)
    if resource == "consignment":
        return consignment(db, ctx, ident, permission, side, True)
    if resource == "organization":
        if ctx.org_id != str(ident):
            fail("FORBIDDEN", "Switch to this organization's context.", status=403)
        return require(db, ctx.user, ctx.org_id, permission)
    model = {
        "assignment": Assignment,
        "receipt": Receipt,
        "inspection": Inspection,
        "closure": receiving.Closure,
        "dispute": Dispute,
        "schedule": Schedule,
        "payment": Payment,
        "allocation": PaymentAllocation,
        "vehicle": Vehicle,
        "attachment": Attachment,
    }[resource]
    row = exists(db, model, ident)
    if resource == "vehicle":
        if row.carrier_organization_id != ctx.org_id:
            fail("NOT_FOUND", "Vehicle not found.", status=404)
        return require(db, ctx.user, ctx.org_id, permission)
    if resource == "attachment":
        trade, _ = attachments.access(db, ctx, row)
        lock_trade(db, trade.id)
        return require(db, ctx.user, ctx.org_id, permission, trade.id)
    if resource == "assignment":
        cn = exists(db, Consignment, row.consignment_id)
        lock_trade(db, cn.trade_id)
        if row.carrier_organization_id != ctx.org_id:
            fail("FORBIDDEN", "Only the selected carrier can decide.", status=403)
        return require(db, ctx.user, ctx.org_id, permission, cn.trade_id)
    if resource == "inspection":
        row = exists(db, Receipt, exists(db, ReceiptLine, row.receipt_line_id).receipt_id)
    if resource in {"receipt", "inspection", "closure"}:
        return consignment(db, ctx, row.consignment_id, permission, side, True)
    if resource == "allocation":
        row = exists(db, Payment, row.payment_id)
    return party(db, ctx, row.trade_id, permission, side, True)


def mutation(path, model, service, resource, permission, side=None, method="POST", status_code=200):
    def endpoint(ident: UUID, request: Request, payload: model, db: Session = Depends(get_db)):
        return mutate(
            request,
            db,
            lambda session, ctx, value: service(session, ctx, str(ident), value),
            payload,
            status=status_code,
            authorize=lambda session, ctx: authorize_resource(
                session, ctx, resource, str(ident), permission, side
            ),
            conflict_code="IDEMPOTENCY_CONFLICT",
        )

    endpoint.__name__ = f"{method.lower()}_{path.replace('/', '_').replace('{ident}', 'record')}"
    router.add_api_route(path, endpoint, methods=[method], status_code=status_code)


mutation(
    "/organizations/{ident}/carrier-profile",
    CarrierProfileInput,
    lambda db, ctx, ident, value: transport.profile(db, ctx, value),
    "organization",
    "carrier_profile.manage",
    method="PUT",
)
mutation(
    "/organizations/{ident}/vehicles",
    VehicleInput,
    lambda db, ctx, ident, value: transport.vehicle(db, ctx, value),
    "organization",
    "vehicle.manage",
    status_code=201,
)
mutation(
    "/vehicles/{ident}",
    VehiclePatch,
    lambda db, ctx, ident, value: transport.vehicle(db, ctx, value, ident),
    "vehicle",
    "vehicle.manage",
    method="PATCH",
)
mutation(
    "/trades/{ident}/consignments",
    ConsignmentPlan,
    allocation.create,
    "trade",
    "consignment.plan",
    "SELLER",
    status_code=201,
)
mutation(
    "/consignments/{ident}",
    ConsignmentPatch,
    allocation.patch,
    "consignment",
    "consignment.plan",
    "SELLER",
    method="PATCH",
)
mutation(
    "/consignments/{ident}/preparations",
    Schema,
    allocation.transition,
    "consignment",
    "consignment.plan",
    "SELLER",
)
mutation(
    "/consignments/{ident}/cancellations",
    Reason,
    lambda db, ctx, ident, value: allocation.transition(db, ctx, ident, value, True),
    "consignment",
    "consignment.cancel",
    "SELLER",
)
mutation(
    "/consignments/{ident}/assignments",
    AssignmentProposal,
    transport.propose,
    "consignment",
    "transport.assign",
    status_code=201,
)
mutation(
    "/assignments/{ident}/decisions",
    AssignmentDecision,
    transport.decide,
    "assignment",
    "assignment.respond",
)
mutation(
    "/consignments/{ident}/events",
    ShipmentEventInput,
    movement.event,
    "consignment",
    "shipment.event.record",
    status_code=201,
)
mutation(
    "/consignments/{ident}/receipts",
    ReceiptInput,
    receiving.receive,
    "consignment",
    "receipt.record",
    "BUYER",
    status_code=201,
)
mutation(
    "/receipts/{ident}/corrections",
    ReceiptCorrection,
    lambda db, ctx, ident, value: receiving.receive(
        db, ctx, exists(db, Receipt, ident).consignment_id, value, ident
    ),
    "receipt",
    "receipt.correct",
    "BUYER",
    status_code=201,
)
mutation(
    "/receipts/{ident}/acceptances",
    InspectionBatch,
    receiving.inspect_goods,
    "receipt",
    "goods.accept",
    "BUYER",
    status_code=201,
)
mutation(
    "/inspection-decisions/{ident}/reversals",
    Reason,
    receiving.reverse,
    "inspection",
    "goods.acceptance.reverse",
    "BUYER",
    status_code=201,
)
mutation(
    "/consignments/{ident}/delivery-closures",
    Notes,
    receiving.close,
    "consignment",
    "receipt.close",
    "BUYER",
    status_code=201,
)
mutation(
    "/delivery-closures/{ident}/reopenings",
    Reason,
    receiving.reopen,
    "closure",
    "receipt.reopen",
    "BUYER",
    status_code=201,
)
mutation(
    "/trades/{ident}/disputes",
    DisputeInput,
    disputes.create,
    "trade",
    "dispute.open",
    status_code=201,
)
for path, model, action, permission in (
    ("comments", Comment, "COMMENT", "dispute.comment"),
    ("resolution-proposals", ResolutionProposal, "PROPOSAL", "dispute.resolve"),
    ("resolution-decisions", ResolutionDecision, "DECISION", "dispute.resolve"),
    ("withdrawals", Reason, "WITHDRAWAL", "dispute.resolve"),
):
    mutation(
        f"/disputes/{{ident}}/{path}",
        model,
        lambda db, ctx, ident, value, event=action: disputes.update(db, ctx, ident, value, event),
        "dispute",
        permission,
    )
mutation(
    "/trades/{ident}/payment-schedules",
    PaymentScheduleInput,
    schedules.propose,
    "trade",
    "payment_schedule.propose",
    status_code=201,
)
mutation(
    "/payment-schedules/{ident}/approvals",
    ScheduleApproval,
    schedules.approve,
    "schedule",
    "payment_schedule.approve",
)
mutation(
    "/trades/{ident}/payments",
    PaymentInput,
    payments.report,
    "trade",
    "payment.report",
    "BUYER",
    status_code=201,
)
for path, model, action in (
    ("acknowledgements", Notes, "ACKNOWLEDGE"),
    ("disputes", Reason, "DISPUTE"),
    ("withdrawals", Reason, "WITHDRAW"),
):
    mutation(
        f"/payments/{{ident}}/{path}",
        model,
        lambda db, ctx, ident, value, decision=action: payments.decide(
            db, ctx, ident, value, decision
        ),
        "payment",
        "payment.report" if action == "WITHDRAW" else "payment.acknowledge",
        "BUYER" if action == "WITHDRAW" else "SELLER",
    )
mutation(
    "/payments/{ident}/allocations",
    PaymentAllocationBatch,
    payments.allocate,
    "payment",
    "payment.allocate",
    "SELLER",
)
mutation(
    "/payment-allocations/{ident}/reversals",
    AllocationReversal,
    payments.reverse,
    "allocation",
    "payment.allocation.reverse",
    "SELLER",
)
mutation(
    "/payments/{ident}/void-requests",
    Reason,
    payments.void_request,
    "payment",
    "payment.void.propose",
)
mutation(
    "/payments/{ident}/void-decisions",
    VoidDecision,
    payments.void_decision,
    "payment",
    "payment.void.approve",
)
mutation(
    "/operational-attachments/{ident}/completions",
    AttachmentCompletion,
    attachments.complete,
    "attachment",
    "attachment.upload",
)


@router.post("/operational-attachments/uploads", status_code=201)
def upload(request: Request, payload: AttachmentUploadInput, db: Session = Depends(get_db)):
    def check(session, ctx):
        if payload.consignment_id:
            return consignment(session, ctx, payload.consignment_id, "attachment.upload", lock=True)
        return party(session, ctx, payload.trade_id, "attachment.upload", lock=True)

    return mutate(
        request,
        db,
        attachments.begin,
        payload,
        status=201,
        authorize=check,
        conflict_code="IDEMPOTENCY_CONFLICT",
    )


@router.get("/carriers")
def carriers(
    request: Request, q: str = "", cursor: UUID | None = None, db: Session = Depends(get_db)
):
    return transport.directory(db, context(request, db), q, cursor)


@router.get("/organizations/{ident}/vehicles")
def vehicles(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authorize_resource(db, ctx, "organization", ident, "vehicle.manage")
    return {
        "items": [
            view(v)
            for v in db.scalars(
                select(Vehicle)
                .where(Vehicle.carrier_organization_id == ctx.org_id)
                .order_by(Vehicle.registration_number)
            )
        ]
    }


@router.get("/organizations/{ident}/carrier-profile")
def carrier_profile(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authorize_resource(db, ctx, "organization", ident, "carrier_profile.manage")
    row = db.scalar(
        select(transport.Carrier).where(transport.Carrier.organization_id == ctx.org_id)
    )
    return view(row) if row else None


@router.get("/organizations/{ident}/drivers")
def drivers(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    authorize_resource(db, ctx, "organization", ident, "assignment.respond")
    rows = db.scalars(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.organization_id == ctx.org_id,
            Membership.status == "ACTIVE",
            User.active.is_(True),
        )
    )
    return {
        "items": [
            {"id": u.id, "display_name": u.display_name}
            for u in rows
            if any(
                g.capability == "DRIVER" and g.permission_code == "shipment.event.record"
                for g in grants(db, membership(db, u, ctx.org_id))
            )
        ]
    }


@router.get("/trades/{ident}/operations")
def operations(ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, _ = party(db, ctx, ident)
    result = views.workspace(db, ctx, trade)
    response.headers["ETag"] = result["etag"]
    return result


@router.get("/consignments/{ident}")
def get_consignment(
    ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)
):
    ctx = context(request, db)
    trade, row, _ = consignment(db, ctx, ident)
    result = views.consignment_view(db, ctx, trade, row)
    response.headers["ETag"] = result["etag"]
    return result


@router.get("/consignments/{ident}/receipt-summary")
def receipt_summary(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, row, side = consignment(db, ctx, ident)
    if not side:
        fail("FORBIDDEN", "Buyer/seller authority is required.", status=403)
    return {
        "lines": receiving.summary(db, row),
        "execution_mode": trade.execution_mode,
        "request_id": ctx.request_id,
    }


@router.get("/consignments/{ident}/events")
def events(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, row, _ = consignment(db, ctx, ident)
    return {
        "items": [
            view(e, trade)
            for e in db.scalars(
                select(movement.Event)
                .where(movement.Event.consignment_id == row.id)
                .order_by(movement.Event.occurred_at, movement.Event.id)
            )
        ],
        "execution_mode": trade.execution_mode,
    }


@router.get("/consignments/{ident}/planning-context")
def planning(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, row, _ = consignment(db, ctx, ident)
    return views.planning_context(db, ctx, trade, row)


@router.get("/assignments/{ident}")
def assignment(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row = exists(db, Assignment, ident)
    trade, cn, side = consignment(db, ctx, row.consignment_id)
    if not side and row.carrier_organization_id != ctx.org_id:
        fail("NOT_FOUND", "Assignment not found.", status=404)
    if (
        not side
        and not views.has(db, ctx, "assignment.respond")
        and (row.id != cn.active_assignment_id or row.driver_user_id != ctx.user.id)
    ):
        fail("NOT_FOUND", "Current task not found.", status=404)
    return {**view(row, trade, ctx), "consignment": views.consignment_view(db, ctx, trade, cn)}


@router.get("/assignments/{ident}/evidence")
def assignment_evidence(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row = exists(db, Assignment, ident)
    if row.carrier_organization_id != ctx.org_id or not (
        views.has(db, ctx, "assignment.respond")
        or (row.driver_user_id == ctx.user.id and views.has(db, ctx, "evidence.read"))
    ):
        fail("NOT_FOUND", "Assignment evidence not found.", status=404)
    trade = exists(db, Trade, exists(db, Consignment, row.consignment_id).trade_id)
    return {
        "assignment": view(row, trade),
        "historical_evidence_only": True,
        "execution_mode": trade.execution_mode,
        "items": [
            view(a, trade)
            for a in db.scalars(
                select(Audit).where(Audit.subject_id == row.id).order_by(Audit.created_at, Audit.id)
            )
        ],
    }


@router.get("/me/transport-tasks")
def tasks(
    request: Request,
    status: str | None = None,
    cursor: UUID | None = None,
    db: Session = Depends(get_db),
):
    ctx = context(request, db)
    query = select(Assignment).where(Assignment.carrier_organization_id == ctx.org_id)
    if status:
        query = query.where(Assignment.status == status)
    if cursor:
        query = query.where(Assignment.id > str(cursor))
    result = []
    from app.trades.errors import TradeError

    from .access import has

    dispatcher = has(db, ctx, "assignment.respond")
    for a in db.scalars(query.order_by(Assignment.id)):
        if not dispatcher and a.driver_user_id != ctx.user.id:
            continue
        try:
            trade, cn, _ = consignment(db, ctx, a.consignment_id)
            if not dispatcher and cn.active_assignment_id != a.id:
                continue
            result.append(
                {**view(a, trade, ctx), "consignment": views.consignment_view(db, ctx, trade, cn)}
            )
        except TradeError:
            continue
        if len(result) == 51:
            break
    return {"items": result[:50], "next_cursor": result[49]["id"] if len(result) > 50 else None}


@router.get("/trades/{ident}/disputes")
def dispute_list(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, _ = party(db, ctx, ident)
    return {
        "items": [
            disputes.dispute_view(db, ctx, trade, d)
            for d in db.scalars(select(Dispute).where(Dispute.trade_id == trade.id))
        ],
        "execution_mode": trade.execution_mode,
    }


@router.get("/disputes/{ident}")
def dispute(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    row = exists(db, Dispute, ident)
    trade, _ = party(db, ctx, row.trade_id)
    return disputes.dispute_view(db, ctx, trade, row)


@router.get("/trades/{ident}/payment-schedule-candidate")
def payment_candidate(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, _ = party(db, ctx, ident, "payment_schedule.propose")
    return schedules.candidate(db, trade)


@router.get("/trades/{ident}/settlement")
def settlement(ident: UUID, request: Request, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, _ = party(db, ctx, ident)
    return payments.settlement(db, ctx, trade)


@router.get("/operational-attachments/{ident}")
def attachment(ident: UUID, request: Request, intent: str = "read", db: Session = Depends(get_db)):
    ctx = context(request, db)
    row = exists(db, Attachment, ident)
    trade, _ = attachments.access(db, ctx, row, intent == "upload")
    return view(row, trade, ctx)


@router.get("/operational-attachments/{ident}/download")
def download(ident: UUID, request: Request, db: Session = Depends(get_db)):
    return attachments.download(db, context(request, db), str(ident))
