"""Tenant/grant-scoped corridor observations, not invented interstate relationship scores."""

from datetime import timedelta
from statistics import median

from sqlalchemy import select

from app.compliance.clock import aware
from app.freight.models import RoutePlan
from app.operations.access import has
from app.operations.models import Consignment, Event
from app.trades.models import Participant


def capture(db, ctx, mode, at):
    participant = (
        select(Participant.id)
        .where(
            Participant.trade_id == Consignment.trade_id, Participant.organization_id == ctx.org_id
        )
        .exists()
    )
    records = db.execute(
        select(RoutePlan, Consignment)
        .join(Consignment, Consignment.id == RoutePlan.consignment_id)
        .where(participant, Consignment.execution_mode == mode)
        .order_by(RoutePlan.created_at.desc())
        .limit(200)
    ).all()
    values, seen = [], set()
    for plan, cn in records:
        if cn.id in seen or not has(db, ctx, "tradetwin.read", cn.trade_id):
            continue
        departure = db.scalar(
            select(Event)
            .where(
                Event.consignment_id == cn.id,
                Event.assignment_id == plan.accepted_assignment_id,
                Event.event_type == "DEPARTED",
            )
            .order_by(Event.created_at)
            .limit(1)
        )
        arrival = db.scalar(
            select(Event)
            .where(
                Event.consignment_id == cn.id,
                Event.assignment_id == plan.accepted_assignment_id,
                Event.event_type == "ARRIVED",
            )
            .order_by(Event.created_at)
            .limit(1)
        )
        if (
            not departure
            or not arrival
            or not at - timedelta(days=90) <= aware(arrival.occurred_at) <= at
            or aware(arrival.occurred_at) <= aware(departure.occurred_at)
            or aware(plan.created_at) > aware(departure.created_at)
        ):
            continue
        route = plan.route_plan_json
        from datetime import datetime

        expected = (
            datetime.fromisoformat(route["estimated_arrival_at"])
            - datetime.fromisoformat(route["planned_departure_at"])
        ).total_seconds()
        actual = (aware(arrival.occurred_at) - aware(departure.occurred_at)).total_seconds()
        if expected <= 0:
            continue
        values.append(
            {
                "state_sequence": route["state_sequence"],
                "extra_seconds": round(max(0, actual - expected)),
                "observed_at": aware(arrival.occurred_at).isoformat(),
            }
        )
        seen.add(cn.id)
    return values


def summary(history, sequence):
    values = [i for i in history if i["state_sequence"] == sequence]
    seconds = [i["extra_seconds"] for i in values]
    return {
        "status": "OBSERVED" if len(seconds) >= 3 else "INSUFFICIENT_HISTORY",
        "sample_count": len(seconds),
        "median_extra_seconds": round(median(seconds)) if seconds else None,
        "ranking_extra_seconds": round(median(seconds)) if len(seconds) >= 3 else None,
        "latest_observation_at": max((i["observed_at"] for i in values), default=None),
        "basis": "Last 90 days, same directed state corridor, "
        "current organization and trade grants. "
        "Driver-reported departure/arrival; not verified GPS or measured border dwell.",
    }
