"""Use the existing durable outbox. A delivery never creates or replays movement."""

from sqlalchemy import select

from app.document_desk.models import Job, Outbox
from app.operations.access import exists
from app.operations.models import Event
from app.trades.terms import digest

from .models import Authorization, MovementProjection

STAGE = "PROJECT_MOVEMENT"


def enqueue(db, ctx, token, event):
    job = Job(
        trade_id=token.trade_id,
        stage=STAGE,
        input_fingerprint=digest({"event_id": event.id, "authorisation_id": token.id}),
        pipeline_version="PH4_MOVEMENT_PROJECTION_V1",
        schema_version="PH4_EVIDENCE_MANIFEST_V1",
        configuration_hash=token.dependency_hash,
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        created_by=ctx.user.id,
        request_json={
            "consignment_id": token.consignment_id,
            "movement_event_id": event.id,
            "authorisation_id": token.id,
        },
    )
    db.add(job)
    db.flush()
    db.add(Outbox(job_id=job.id))


def deliver(db, ctx, job):
    event = exists(db, Event, job.request_json["movement_event_id"])
    token = exists(db, Authorization, job.request_json["authorisation_id"])
    if token.consumed_event_id != event.id:
        raise ValueError("Projection requires the already committed authorisation consumption")
    previous = db.scalar(
        select(MovementProjection).where(MovementProjection.movement_event_id == event.id)
    )
    if previous:
        return previous
    body = {
        "schema_version": "PH4_MOVEMENT_PROJECTION_V1",
        "event_id": event.id,
        "event_type": event.event_type,
        "event_hash": event.request_hash,
        "execution_mode": event.execution_mode,
        "evaluation_hash": token.evaluation_hash,
        "packet_hash": token.packet_hash,
        "authorisation_id": token.id,
    }
    row = MovementProjection(
        movement_event_id=event.id,
        authorisation_id=token.id,
        projection_json=body,
        content_hash=digest(body),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    return row
