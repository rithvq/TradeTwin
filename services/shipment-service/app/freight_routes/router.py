"""Existing authenticated organization context and command transaction boundary."""

import os
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.freight.access import base_context, planning
from app.freight.models import Location
from app.operations.access import fail
from app.trades.transactions import context, mutate

from . import jobs
from .context import confirmed_pin, nominated_truck
from .schemas import StudyInput

router = APIRouter(tags=["India freight route intelligence"])


@router.post("/consignments/{ident}/freight-route-studies", status_code=202)
def request_study(
    ident: UUID, request: Request, payload: StudyInput, db: Session = Depends(get_db)
):
    return mutate(
        request,
        db,
        lambda session, actor, value: jobs.request(session, actor, str(ident), value),
        payload,
        status=202,
        authorize=lambda session, actor: planning(
            session, actor, str(ident), "tradetwin.plan.prepare", True
        ),
    )


@router.get("/consignments/{ident}/freight-route-intelligence")
def context_view(ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    actor = context(request, db)
    trade, cn = planning(db, actor, str(ident))
    base = base_context(db, trade, cn)
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "consignment_id": cn.id,
        "execution_mode": trade.execution_mode,
        "pickup_state_code": cn.pickup_address_snapshot["state_code"],
        "drop_state_code": cn.delivery_address_snapshot["state_code"],
        "pins_confirmed": all(
            confirmed_pin(db.get(Location, base[key])) if base[key] else False
            for key in ("pickup_location_revision_id", "drop_location_revision_id")
        ),
        "truck": nominated_truck(db, cn),
        "cargo_weight_kg": base["cargo_snapshot"]["gross_weight_kg"],
        "live_routing_configured": bool(os.getenv("ORS_API_KEY"))
        and os.getenv("ALLOW_EXTERNAL_ROUTING", "false").lower() == "true",
        "weather_plan": os.getenv("FREIGHT_WEATHER_PLAN", "NON_COMMERCIAL"),
        "studies": jobs.listing(db, actor, cn.id),
    }


@router.get("/freight-route-studies/{ident}")
def study(ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    return jobs.read(db, context(request, db), str(ident))


@router.get("/freight-route-studies/{ident}/evidence-manifest")
def manifest(ident: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    actor = context(request, db)
    row, _, _ = jobs.exact(db, actor, str(ident))
    if row.source_mode == "RETAINED" and not row.input_json["dataset"]["data"]["export_allowed"]:
        fail(
            "SOURCE_EXPORT_NOT_PERMITTED",
            "This retained source does not permit export.",
            status=403,
        )
    return jobs.read(db, actor, str(ident))
