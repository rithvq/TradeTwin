"""Source identity, independent review, and immutable incident history."""

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.compliance.clock import aware, instant
from app.compliance.ledger import independent, record, view
from app.operations.access import exists, fail, match
from app.operations.ledger import touch
from app.trades.access import require
from app.trades.terms import digest

from .models import Connection, EventAction, EventRevision, Incident, SourceItem, Tombstone


def upstream_key(value):
    parts = value.strip().split(",")
    try:
        sent = datetime.fromisoformat(parts[2])
        if len(parts) != 3 or sent.tzinfo is None:
            raise ValueError("Invalid upstream identity")
    except (ValueError, IndexError):
        fail(
            "UPSTREAM_IDENTITY_INVALID",
            "Use sender,identifier,sent with an explicit timezone.",
            status=422,
        )
    return ",".join([parts[0], parts[1], aware(sent).isoformat()])


def access(db, ctx, ident):
    row = exists(db, Incident, ident)
    if row.owner_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Incident not found.", status=404)
    require(db, ctx.user, ctx.org_id, "regulation.source.register")
    return row


def incident(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.source.register")
    if payload.consignment_id:
        from app.operations.access import consignment

        trade, _, _ = consignment(db, ctx, payload.consignment_id)
        if trade.execution_mode != payload.environment:
            fail("MODE_MISMATCH", "Incident inherits its consignment's mode.")
    if payload.visibility == "CONSIGNMENT_ONLY" and not payload.consignment_id:
        fail("VALIDATION_ERROR", "A consignment-only incident requires a consignment.", status=422)
    row = Incident(
        environment=payload.environment,
        owner_organisation_id=ctx.org_id,
        consignment_id=str(payload.consignment_id) if payload.consignment_id else None,
        visibility=payload.visibility,
        created_by=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "CORRIDOR_INCIDENT_CREATED", row)
    return {**view(row), "etag": f'"{row.row_version}"'}


def create(db, ctx, ident, payload):
    head = access(db, ctx, ident)
    match(ctx, head)
    item = exists(db, SourceItem, payload.source_item_id)
    connection = exists(db, Connection, item.source_connection_id)
    if payload.source_sent_at > instant(db):
        fail("VALIDATION_ERROR", "Publisher sent time cannot be in the future.", status=422)
    if payload.geography.dataset_revision_id:
        from app.freight.models import Dataset

        dataset = exists(db, Dataset, payload.geography.dataset_revision_id)
        if dataset.execution_mode != head.environment or not set(payload.geography.edge_keys) <= {
            e["edge_key"] for e in dataset.dataset_json["edges"]
        }:
            fail(
                "GEOGRAPHY_SCOPE_INVALID",
                "Exact event edges must exist in the retained dataset and mode.",
            )
    if connection.owner_organisation_id != ctx.org_id or connection.environment != head.environment:
        fail("NOT_FOUND", "Source version not found in this scope.", status=404)
    if head.environment == "PRODUCTION" and (
        payload.source_status not in {"ACTUAL", "NON_CAP"}
        or payload.report_basis == "SIMULATION"
        or payload.geography.basis == "SIMULATION"
    ):
        fail("MODE_MISMATCH", "Exercise/test/simulation content cannot become a production event.")
    if connection.source_kind == "CARRIER_OBSERVATION" and head.visibility == "PUBLIC_APPROVED":
        fail(
            "SOURCE_VISIBILITY_INVALID",
            "Carrier observations are private, never implicitly public.",
        )
    data = payload.model_dump(mode="json")
    number = (
        db.scalar(
            select(func.max(EventRevision.revision_number)).where(
                EventRevision.incident_id == head.id
            )
        )
        or 0
    ) + 1
    row = EventRevision(
        incident_id=head.id,
        revision_number=number,
        source_item_id=item.id,
        event_kind=payload.event_kind,
        assessed_effective_from=payload.assessed_effective_from,
        assessed_effective_until=payload.assessed_effective_until,
        operational_review_due_at=payload.operational_review_due_at,
        event_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "CORRIDOR_EVENT_DRAFTED", row)
    touch(head)
    return {**view(row), "incident_etag": f'"{head.row_version}"', "state": "PENDING_REVIEW"}


def history(db, row):
    return list(
        db.scalars(
            select(EventAction)
            .where(EventAction.event_revision_id == row.id)
            .order_by(EventAction.sequence_number)
        )
    )


def scopes(row):
    geo = row.event_json["geography"]
    return sorted(
        set(
            ["state:" + s for s in geo["state_codes"]]
            + [f"edge:{geo['dataset_revision_id']}:{e}" for e in geo["edge_keys"]]
        )
    ) or ["*"]


def action(db, ctx, row, kind, payload):
    event = EventAction(
        sequence_number=(
            db.scalar(
                select(func.max(EventAction.sequence_number)).where(
                    EventAction.event_revision_id == row.id
                )
            )
            or 0
        )
        + 1,
        event_revision_id=row.id,
        action=kind,
        event_hash=row.content_hash,
        actor_user_id=ctx.user.id,
        actor_organisation_id=ctx.org_id,
        action_json=payload.model_dump(mode="json"),
    )
    db.add(event)
    record(db, ctx, "CORRIDOR_EVENT_" + kind, row)


def review(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.review")
    row = exists(db, EventRevision, ident)
    # Reviewers operate on the same source-owning organisation, with independent capability.
    head = exists(db, Incident, row.incident_id)
    if head.owner_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Review record not found.", status=404)
    independent(ctx, row.created_by_user_id)
    if row.content_hash != payload.content_hash:
        fail("EXACT_HASH_REQUIRED", "Review the exact event revision.", status=412)
    action(db, ctx, row, "APPROVED" if payload.decision == "APPROVE" else "RETURNED", payload)
    return {
        "id": row.id,
        "state": "REVIEWED" if payload.decision == "APPROVE" else "PENDING_REVIEW",
    }


def publish(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.publish")
    row = exists(db, EventRevision, ident)
    head = exists(db, Incident, row.incident_id)
    if head.owner_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Event not found.", status=404)
    if row.content_hash != payload.content_hash:
        fail("EXACT_HASH_REQUIRED", "Publish the exact reviewed revision.", status=412)
    independent(ctx, row.created_by_user_id)
    actions = history(db, row)
    if not actions or actions[-1].action != "APPROVED":
        fail(
            "INDEPENDENT_REVIEW_REQUIRED",
            "Event publication requires current independent approval.",
        )
    from app.trades.models import User

    approval = actions[-1]
    reviewer = exists(db, User, approval.actor_user_id)
    require(db, reviewer, approval.actor_organisation_id, "regulation.pack.review")
    if not reviewer.active:
        fail("INDEPENDENT_REVIEW_REQUIRED", "The approving account is inactive.")
    item = exists(db, SourceItem, row.source_item_id)
    connection = exists(db, Connection, item.source_connection_id)
    if connection.status != "CONFIGURED":
        fail("SOURCE_NOT_CONFIGURED", "Source ingress is disabled or unapproved.")
    identity = upstream_key(
        ",".join(
            row.event_json[k] for k in ("source_sender", "source_identifier", "source_sent_at")
        )
    )
    tombstone = db.scalar(
        select(Tombstone).where(
            Tombstone.source_connection_id == connection.id, Tombstone.upstream_key == identity
        )
    )
    if tombstone:
        fail(
            "UPSTREAM_SUPERSEDED",
            "A prior update/cancellation references this exact message; "
            "late delivery cannot resurrect it.",
        )
    for existing in db.scalars(
        select(EventRevision).where(EventRevision.source_item_id == item.id)
    ):
        if existing.id != row.id and any(a.action == "PUBLISHED" for a in history(db, existing)):
            fail(
                "SOURCE_MESSAGE_ALREADY_PUBLISHED",
                "This source item already has a published interpretation; "
                "revise its incident instead of duplicating evidence.",
            )
    for reference in row.event_json["upstream_references"]:
        if row.event_json["source_message_type"] not in {"UPDATE", "CANCEL"}:
            break
        db.add(
            Tombstone(
                source_connection_id=connection.id,
                upstream_key=upstream_key(reference),
                message_hash=row.content_hash,
                source_item_id=item.id,
                action=row.event_json["source_message_type"],
            )
        )
    old = db.get(EventRevision, head.current_revision_id) if head.current_revision_id else None
    if old and row.revision_number <= old.revision_number:
        fail("EVENT_REVISION_STALE", "An older local revision cannot replace the published head.")
    if old:
        action(db, ctx, old, "SUPERSEDED", payload)
    head.current_revision_id = row.id
    touch(head)
    action(db, ctx, row, "PUBLISHED", payload)
    from .projection import bump_scopes

    bump_scopes(db, head.environment, [*scopes(row), *(scopes(old) if old else [])])
    return {**view(row), "state": state(db, row), "incident_etag": f'"{head.row_version}"'}


def withdraw(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.publish")
    row = exists(db, EventRevision, ident)
    head = exists(db, Incident, row.incident_id)
    if head.owner_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Event not found.", status=404)
    action(db, ctx, row, "WITHDRAWN", payload)
    from .projection import bump_scopes

    bump_scopes(db, head.environment, scopes(row))
    return {"id": row.id, "state": "WITHDRAWN", "reopening_proven": False}


def state(db, row, at=None):
    at = at or instant(db)
    actions = history(db, row)
    if not any(a.action == "PUBLISHED" for a in actions):
        return "PENDING_REVIEW"
    if any(a.action == "REOPENING_EVIDENCE_ADDED" for a in actions):
        return "RESOLVED"
    if actions[-1].action in {"WITHDRAWN", "SUPERSEDED"}:
        return actions[-1].action
    if row.event_json["source_message_type"] == "CANCEL":
        return "WITHDRAWN"
    if aware(row.operational_review_due_at) <= at:
        return "STALE"
    if row.assessed_effective_until and at >= aware(row.assessed_effective_until):
        return "EXPIRED"
    if row.assessed_effective_from and at < aware(row.assessed_effective_from):
        return "FUTURE"
    return "ACTIVE"


def reopening(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.review")
    original = exists(db, EventRevision, ident)
    head = exists(db, Incident, original.incident_id)
    if head.owner_organisation_id != ctx.org_id or payload.content_hash != original.content_hash:
        fail("NOT_FOUND", "Exact original event not found.", status=404)
    independent(ctx, original.created_by_user_id)
    new = exists(db, EventRevision, payload.reopening_event_revision_id)
    new_head = exists(db, Incident, new.incident_id)
    if (
        new_head.environment != head.environment
        or new.event_kind != "REOPENING_NOTICE"
        or state(db, new) != "ACTIVE"
        or new.source_item_id == original.source_item_id
    ):
        fail(
            "REOPENING_EVIDENCE_INVALID",
            "Use an independently reviewed, current positive reopening notice in the same mode.",
        )
    independent(ctx, new.created_by_user_id)
    item = exists(db, SourceItem, new.source_item_id)
    connection = exists(db, Connection, item.source_connection_id)
    if connection.status != "CONFIGURED" or instant(db) >= aware(
        item.source_issued_at or item.retrieved_at
    ) + timedelta(seconds=connection.connection_json["maximum_item_age_seconds"]):
        fail(
            "REOPENING_EVIDENCE_INVALID", "Positive reopening evidence must have a current source."
        )
    geo, reopened = original.event_json["geography"], new.event_json["geography"]
    covers = False
    if geo["geometry_kind"] == reopened["geometry_kind"] == "ROAD_EDGE_SET":
        covers = geo["dataset_revision_id"] == reopened["dataset_revision_id"] and set(
            geo["edge_keys"]
        ) <= set(reopened["edge_keys"])
    elif geo["geojson"] and reopened["geojson"]:
        from .geometry import validate_geometry

        covers = validate_geometry(reopened["geojson"]).covers(validate_geometry(geo["geojson"]))
    if (
        not covers
        or reopened["direction"] not in {"BOTH", geo["direction"]}
        or geo["direction"] == "UNKNOWN"
    ):
        fail(
            "REOPENING_SCOPE_MISMATCH",
            "Positive evidence must cover the exact original geography and direction.",
        )
    if (
        original.event_json["vehicle_profile_codes"] != new.event_json["vehicle_profile_codes"]
        or original.event_json["cargo_profile_codes"] != new.event_json["cargo_profile_codes"]
    ):
        fail(
            "REOPENING_SCOPE_MISMATCH",
            "Vehicle and cargo classes must match the original restriction.",
        )
    action(db, ctx, original, "REOPENING_EVIDENCE_ADDED", payload)
    from .projection import bump_scopes

    bump_scopes(db, head.environment, scopes(original))
    return {
        "id": original.id,
        "state": "RESOLVED",
        "movement_authorised": False,
        "contract_changed": False,
    }
