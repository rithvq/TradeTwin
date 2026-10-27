from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.trades.schemas import Schema
from app.trades.transactions import context, mutate

from . import service

router = APIRouter(tags=["Integrated simulation demo"])


class CreateDemo(Schema):
    fresh: bool = False


class Step(Schema):
    step_code: Literal[
        "CORRIDOR_CHANGE",
        "ACCEPT_FREIGHT",
        "PICKUP_RELEASE",
        "PICKUP",
        "DEPARTURE_RELEASE",
        "DEPART",
        "RECEIVE",
        "PAYMENT",
    ]


@router.post("/demo-sessions", status_code=202)
def launch(request: Request, payload: CreateDemo, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        service.launch,
        payload,
        organization_required=False,
        status=202,
        authorize=lambda *_: service.enabled(),
    )


@router.get("/demo-sessions/{ident}")
def view(ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    return service.view(db, context(request, db, False), str(ident))


@router.post("/demo-sessions/{ident}/steps", status_code=202)
def step(ident: UUID, request: Request, payload: Step, db: Session = Depends(get_db)):
    return mutate(
        request,
        db,
        lambda s, c, p: service.step(s, c, str(ident), p),
        payload,
        organization_required=False,
        status=202,
        authorize=lambda s, c: service.owned(s, c, str(ident)),
    )
