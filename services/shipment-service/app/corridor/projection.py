"""Scoped epochs and trusted-time projection feed synchronous release dependencies."""

from datetime import timedelta

from sqlalchemy import inspect, select

from app.compliance.clock import aware, instant
from app.freight.models import PlanHead, RoutePlan
from app.trades.terms import digest

from . import events, governance
from .models import Connection, EventRevision, Incident, Policy, ScopeHead, SourceHealth, SourceItem


def bump_scopes(db, mode, keys):
    # Publication holds the existing exclusive registry lock; dispatch holds it shared.
    # Epoch values are route-scoped, so unrelated publication does not stale every trade.
    for key in sorted(set(keys)):
        head = db.get(ScopeHead, (mode, key))
        if head is None:
            head = ScopeHead(environment=mode, scope_key=key, epoch=0)
            db.add(head)
        head.epoch += 1
    db.flush()


def plan(db, cn):
    head = db.scalar(select(PlanHead).where(PlanHead.consignment_id == cn.id))
    return (
        db.get(RoutePlan, head.current_revision_id) if head and head.current_revision_id else None
    )


def capture(db, trade, cn, route=None, at=None):
    at = at or instant(db)
    if not inspect(db.get_bind()).has_table(Incident.__tablename__):
        return None
    mode = trade.execution_mode
    current = plan(db, cn) if route is None else None
    route = route or (current.route_plan_json["route_snapshot"] if current else None)
    states = set(
        (route or {}).get("state_sequence")
        or [cn.pickup_address_snapshot["state_code"], cn.delivery_address_snapshot["state_code"]]
    )
    edge_keys = set((route or {}).get("ordered_edge_keys", []))
    dataset = (route or {}).get("dataset_revision_id")
    scope_keys = [
        "*",
        *["state:" + s for s in sorted(states)],
        *[f"edge:{dataset}:{k}" for k in sorted(edge_keys)],
    ]
    epochs = {
        key: head.epoch if (head := db.get(ScopeHead, (mode, key))) else 0 for key in scope_keys
    }
    policies = []
    boundaries = []
    for policy in db.scalars(select(Policy).where(Policy.environment == mode).order_by(Policy.id)):
        if policy.policy_json["state_codes"] and not states.intersection(
            policy.policy_json["state_codes"]
        ):
            continue
        if not governance.published(db, policy):
            continue
        if aware(policy.effective_from) > at:
            boundaries.append(aware(policy.effective_from))
        if governance.active(db, policy, at):
            policies.append({"id": policy.id, "hash": policy.content_hash, **policy.policy_json})
            boundaries.append(aware(policy.effective_until))
    published = []
    for event, incident in db.execute(
        select(EventRevision, Incident)
        .join(Incident, EventRevision.incident_id == Incident.id)
        .where(Incident.environment == mode)
        .order_by(EventRevision.id)
    ):
        if incident.consignment_id and incident.consignment_id != cn.id:
            continue
        if incident.visibility != "PUBLIC_APPROVED" and incident.owner_organisation_id not in {
            cn.coordinating_organization_id,
            trade.creator_organization_id,
        }:
            continue
        event_scopes = set(events.scopes(event))
        if "*" not in event_scopes and not event_scopes.intersection(scope_keys):
            continue
        state = events.state(db, event, at)
        if state in {"PENDING_REVIEW", "RESOLVED"}:
            continue
        connection = db.get(
            Connection, db.get(SourceItem, event.source_item_id).source_connection_id
        )
        item = db.get(SourceItem, event.source_item_id)
        if connection.environment != mode:
            continue
        source_age_from = aware(item.source_issued_at or item.retrieved_at)
        source_stale = at >= source_age_from + timedelta(
            seconds=connection.connection_json["maximum_item_age_seconds"]
        )
        age_until = source_age_from + timedelta(
            seconds=connection.connection_json["maximum_item_age_seconds"]
        )
        if age_until > at:
            boundaries.append(age_until)
        for time in (
            event.assessed_effective_from,
            event.assessed_effective_until,
            event.operational_review_due_at,
        ):
            if time and aware(time) > at:
                boundaries.append(aware(time))
        # Never discard an unresolved closure because its publisher/source became stale.
        if state in {"WITHDRAWN", "SUPERSEDED", "EXPIRED"} and event.event_kind not in {
            "ROAD_CLOSURE",
            "TRAFFIC_RESTRICTION",
        }:
            continue
        published.append(
            {
                "id": event.id,
                "incident_id": incident.id,
                "hash": event.content_hash,
                "state": state,
                "source_stale": source_stale,
                "source_kind": connection.source_kind,
                "source_connection_id": connection.id,
                "source_item_id": item.id,
                "source_reference": item.item_json["source_reference"],
                "source_issued_at": source_age_from.isoformat(),
                "connection_status": connection.status,
                "source_item_hash": item.content_hash,
                **event.event_json,
            }
        )
    required = sorted(set(k for p in policies for k in p["required_source_kinds"]))
    health = []
    for connection in db.scalars(
        select(Connection).where(Connection.environment == mode).order_by(Connection.id)
    ):
        if not states.intersection(connection.connection_json["covered_state_codes"]):
            continue
        # Private carrier observations are not public source coverage.
        if connection.source_kind == "CARRIER_OBSERVATION":
            continue
        item = db.get(SourceHealth, connection.id)
        freshness = (
            aware(item.last_success_at)
            + timedelta(seconds=connection.connection_json["maximum_item_age_seconds"])
            if item and item.last_success_at
            else None
        )
        status = item.coverage_status if item else "NOT_CONFIGURED"
        if freshness and at >= freshness:
            status = "STALE"
        elif freshness:
            boundaries.append(freshness)
        health.append(
            {
                "source_connection_id": connection.id,
                "source_kind": connection.source_kind,
                "state_codes": connection.connection_json["covered_state_codes"],
                "event_kinds": connection.connection_json["covered_event_kinds"],
                "status": status,
                "health_version": item.health_version if item else 0,
                "last_success_at": aware(item.last_success_at).isoformat()
                if item and item.last_success_at
                else None,
                "configured": connection.status == "CONFIGURED",
            }
        )
    missing = [
        {"state_code": state, "source_kind": kind}
        for state in sorted(states)
        for kind in required
        if not any(
            h["configured"]
            and h["status"] == "CURRENT"
            and h["source_kind"] == kind
            and state in h["state_codes"]
            for h in health
        )
    ]
    coverage = {
        "status": "NOT_CONFIGURED"
        if not health
        else "PARTIAL"
        if missing or any(h["status"] != "CURRENT" for h in health)
        else "CURRENT",
        "required_source_kinds": required,
        "checked_sources": health,
        "missing_scopes": missing,
        "limitations": [
            "Manual observations do not establish exhaustive source coverage.",
            "No matching alerts in these checked sources does not mean absence of hazards.",
        ],
    }
    value = {
        "schema_version": "DYNAMIC_CORRIDOR_CONTEXT_V1",
        "execution_mode": mode,
        "route_plan_revision_id": current.id if current else None,
        "route_hash": digest(route) if route else None,
        "scope_epochs": epochs,
        "policies": policies,
        "events": published,
        "coverage": coverage,
    }
    return {
        **value,
        "projection_hash": digest(value),
        "valid_until": min(boundaries).isoformat() if boundaries else None,
    }


def dependency(db, trade, cn):
    captured = capture(db, trade, cn)
    if captured is None:
        return None
    # The clock itself is not hashed. Trusted-time state/health changes are.
    from .impact import evaluate_plan

    current = plan(db, cn)
    result = evaluate_plan(db, current, captured) if current else None
    return {
        "projection_hash": captured["projection_hash"],
        "scope_epochs": captured["scope_epochs"],
        "valid_until": captured["valid_until"],
        "outcome": result["outcome"] if result else "NOT_ASSESSED",
        "event_ids": [e["id"] for e in captured["events"]],
    }
