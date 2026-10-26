from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db

from . import agreements, profiles
from .access import actor, aware, organization, require, trade_access
from .errors import TradeError
from .ledger import trade_view
from .models import Amendment, Audit, Membership, Participant, Trade, User
from .reference import ROLE_PERMISSIONS, STATES, UQC
from .schemas import (
    AmendmentCreate,
    Confirmation,
    DraftPatch,
    LocationCreate,
    MembershipChange,
    OrganizationDraft,
    Publish,
    Reason,
    RegistrationCreate,
    Rejection,
    TradeCreate,
    TradeView,
)
from .transactions import context, mutate

router = APIRouter(prefix="/api/v1", tags=["Commercial agreements"])


@router.get("/me")
def me(db: Session = Depends(get_db)):
    result = profiles.me(db, actor(db))
    db.commit()
    return result


@router.get("/reference-data")
def reference_data(db: Session = Depends(get_db)):
    actor(db)
    db.commit()
    return {
        "states": STATES,
        "unit_codes": UQC,
        "capability_permissions": {key: sorted(value) for key, value in ROLE_PERMISSIONS.items()},
        "operational_timezone": "Asia/Kolkata",
    }


@router.post("/organizations", status_code=201)
def create_org(request: Request, payload: OrganizationDraft, db: Session = Depends(get_db)):
    return mutate(request, db, profiles.create_organization, payload, False, 201)


@router.get("/organizations/{organization_id}")
def get_org(
    organization_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)
):
    ctx = context(request, db)
    if ctx.org_id != str(organization_id):
        raise TradeError("FORBIDDEN", "Switch to an authorised organisation context.", 403)
    result = profiles.profile_view(db, organization(db, ctx.user, ctx.org_id))
    response.headers["ETag"] = result["etag"]
    db.commit()
    return result


def same_org(request, organization_id):
    if request.headers.get("X-Organization-Id") != str(organization_id):
        raise TradeError("FORBIDDEN", "Organisation context does not match the resource.", 403)


@router.patch("/organizations/{organization_id}")
def patch_org(
    organization_id: UUID,
    request: Request,
    payload: OrganizationDraft,
    db: Session = Depends(get_db),
):
    same_org(request, organization_id)
    return mutate(
        request,
        db,
        lambda session, ctx, value: profiles.edit_organization(
            session, ctx, str(organization_id), value
        ),
        payload,
    )


@router.post("/organizations/{organization_id}/registrations", status_code=201)
def register(
    organization_id: UUID,
    request: Request,
    payload: RegistrationCreate,
    db: Session = Depends(get_db),
):
    same_org(request, organization_id)
    return mutate(
        request,
        db,
        lambda session, ctx, value: profiles.add_registration(
            session, ctx, str(organization_id), value
        ),
        payload,
        status=201,
    )


@router.post("/organizations/{organization_id}/locations", status_code=201)
def location(
    organization_id: UUID, request: Request, payload: LocationCreate, db: Session = Depends(get_db)
):
    same_org(request, organization_id)
    return mutate(
        request,
        db,
        lambda session, ctx, value: profiles.add_location(
            session, ctx, str(organization_id), value
        ),
        payload,
        status=201,
    )


@router.post("/organizations/{organization_id}/members")
def member(
    organization_id: UUID,
    request: Request,
    payload: MembershipChange,
    db: Session = Depends(get_db),
):
    same_org(request, organization_id)
    return mutate(
        request,
        db,
        lambda session, ctx, value: profiles.change_membership(
            session, ctx, str(organization_id), value
        ),
        payload,
    )


@router.get("/organizations/{organization_id}/members")
def members(organization_id: UUID, request: Request, db: Session = Depends(get_db)):
    same_org(request, organization_id)
    ctx = context(request, db)
    require(db, ctx.user, ctx.org_id, "members.manage")
    rows = db.execute(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(Membership.organization_id == ctx.org_id)
    ).all()
    return [
        {"user_id": user.id, "display_name": user.display_name, "status": membership.status}
        for membership, user in rows
    ]


@router.get("/trading-partners")
def partners(q: str = "", db: Session = Depends(get_db)):
    actor(db)
    result = profiles.trading_partners(db, q)
    db.commit()
    return {"items": result}


@router.post("/trades", response_model=TradeView, status_code=201)
def create(request: Request, payload: TradeCreate, db: Session = Depends(get_db)):
    return mutate(request, db, agreements.create_trade, payload, status=201)


@router.get("/trades")
def listing(
    request: Request,
    role: Literal["SELLER", "BUYER"] = "SELLER",
    status: Literal["DRAFT", "OFFERED", "CONFIRMED", "CANCELLED"] | None = None,
    cursor: UUID | None = None,
    db: Session = Depends(get_db),
):
    ctx = context(request, db)
    query = (
        select(Trade)
        .join(Participant, Participant.trade_id == Trade.id)
        .where(Participant.organization_id == ctx.org_id, Participant.participant_role == role)
    )
    if status:
        query = query.where(Trade.agreement_status == status)
    if cursor:
        query = query.where(Trade.id > str(cursor))
    rows = list(db.scalars(query.order_by(Trade.id).limit(51)))
    items = []
    for row in rows[:50]:
        try:
            trade_access(db, ctx.user, ctx.org_id, row.id)
            items.append(trade_view(db, ctx, row))
        except TradeError:
            continue
    db.commit()
    return {"items": items, "next_cursor": rows[49].id if len(rows) > 50 else None}


@router.get("/trades/{trade_id}", response_model=TradeView)
def get_trade(trade_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    ctx = context(request, db)
    trade, _ = trade_access(db, ctx.user, ctx.org_id, str(trade_id))
    result = trade_view(db, ctx, trade)
    response.headers["ETag"] = result["etag"]
    db.commit()
    return result


@router.patch("/trades/{trade_id}/draft", response_model=TradeView)
def patch(trade_id: UUID, request: Request, payload: DraftPatch, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.patch_draft(session, ctx, str(trade_id), value),
        payload,
    )


@router.post("/trades/{trade_id}/offers", response_model=TradeView)
def publish(trade_id: UUID, request: Request, payload: Publish, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.publish(session, ctx, str(trade_id), value),
        payload,
    )


@router.post("/offers/{offer_id}/withdrawals", response_model=TradeView)
def withdraw(offer_id: UUID, request: Request, payload: Reason, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.withdraw_offer(session, ctx, str(offer_id), value),
        payload,
    )


@router.post("/offers/{offer_id}/confirmations")
def confirm(offer_id: UUID, request: Request, payload: Confirmation, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.decide(session, ctx, str(offer_id), value, "ACCEPT"),
        payload,
    )


@router.post("/offers/{offer_id}/rejections")
def reject(offer_id: UUID, request: Request, payload: Rejection, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.decide(session, ctx, str(offer_id), value, "REJECT"),
        payload,
    )


@router.post("/trades/{trade_id}/amendments", response_model=TradeView)
def amend(
    trade_id: UUID, request: Request, payload: AmendmentCreate, db: Session = Depends(get_db)
):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.create_amendment(session, ctx, str(trade_id), value),
        payload,
    )


def amendment_trade(db, request, amendment_id):
    ctx = context(request, db)
    row = db.get(Amendment, str(amendment_id))
    if not row:
        raise TradeError("NOT_FOUND", "Proposal not found.", 404)
    trade_access(db, ctx.user, ctx.org_id, row.trade_id)
    return row.trade_id


@router.patch("/amendments/{amendment_id}/draft", response_model=TradeView)
def amend_patch(
    amendment_id: UUID, request: Request, payload: DraftPatch, db: Session = Depends(get_db)
):
    trade_id = amendment_trade(db, request, amendment_id)
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.patch_draft(
            session, ctx, trade_id, value, str(amendment_id)
        ),
        payload,
    )


@router.post("/amendments/{amendment_id}/offers", response_model=TradeView)
def amend_publish(
    amendment_id: UUID, request: Request, payload: Publish, db: Session = Depends(get_db)
):
    trade_id = amendment_trade(db, request, amendment_id)
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.publish(
            session, ctx, trade_id, value, str(amendment_id)
        ),
        payload,
    )


@router.post("/amendments/{amendment_id}/withdrawals", response_model=TradeView)
def amend_withdraw(
    amendment_id: UUID, request: Request, payload: Reason, db: Session = Depends(get_db)
):
    return mutate(
        request,
        db,
        lambda session, ctx, value: agreements.withdraw_amendment(
            session, ctx, str(amendment_id), value
        ),
        payload,
    )


@router.get("/trades/{trade_id}/evidence-events")
def evidence(
    trade_id: UUID,
    request: Request,
    cursor: UUID | None = None,
    consignment_id: UUID | None = None,
    subject_type: str | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    ctx = context(request, db)
    trade_access(db, ctx.user, ctx.org_id, str(trade_id), "evidence.read")
    query = select(Audit).where(Audit.trade_id == str(trade_id))
    if consignment_id:
        query = query.where(Audit.consignment_id == str(consignment_id))
    if subject_type:
        query = query.where(Audit.subject_type == subject_type)
    if document_id:
        query = query.where(Audit.document_id == str(document_id))
    if document_version_id:
        query = query.where(Audit.document_version_id == str(document_version_id))
    if cursor:
        previous = db.get(Audit, str(cursor))
        if not previous or previous.trade_id != str(trade_id):
            raise TradeError("NOT_FOUND", "History cursor not found.", 404)
        from sqlalchemy import and_, or_

        query = query.where(
            or_(
                Audit.created_at > previous.created_at,
                and_(Audit.created_at == previous.created_at, Audit.id > previous.id),
            )
        )
    from app.document_desk import access as document_access

    rows = []
    for row in db.scalars(query.order_by(Audit.created_at, Audit.id)):
        if row.document_id:
            try:
                document_access.document(db, ctx, row.document_id)
            except TradeError:
                continue
        rows.append(row)
        if len(rows) == 51:
            break
    return {
        "items": [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "actor_name": db.get(User, row.actor_user_id).display_name,
                "actor_organization_id": row.actor_organization_id,
                "action": row.action,
                "occurred_at": aware(row.created_at).isoformat(),
                "revision_id": row.revision_id,
                "subject_id": row.subject_id,
                "subject_type": row.subject_type,
                "consignment_id": row.consignment_id,
                "document_id": row.document_id,
                "document_version_id": row.document_version_id,
                "execution_mode": row.execution_mode,
                "terms_hash": row.terms_hash,
                "summary": row.redacted_summary_json,
            }
            for row in rows[:50]
        ],
        "next_cursor": rows[49].id if len(rows) > 50 else None,
    }


from app.operations.router import router as operations_router  # noqa: E402

router.include_router(operations_router)

from app.document_desk.router import router as document_router  # noqa: E402

router.include_router(document_router)

from app.compliance.router import router as compliance_router  # noqa: E402

router.include_router(compliance_router)

from app.freight.router import router as freight_router  # noqa: E402

router.include_router(freight_router)

from app.freight_routes.router import router as freight_routes_router  # noqa: E402

router.include_router(freight_routes_router)

from app.corridor.router import router as corridor_router  # noqa: E402

router.include_router(corridor_router)

from app.product.router import router as product_router  # noqa: E402

router.include_router(product_router)
