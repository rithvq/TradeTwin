import os
from datetime import timedelta

from sqlalchemy import select

from app.compliance.clock import aware, instant
from app.document_desk.models import Job, Outbox
from app.operations.access import exists, fail
from app.trades.models import Organization, User, uid
from app.trades.terms import digest

from .catalog import STEPS, VERSION
from .models import Command, Launch

FRESH_FOR = timedelta(minutes=10)


def enabled():
    if os.getenv("IN_APP_DEMO_ENABLED", "false").lower() != "true":
        fail("DEMO_DISABLED", "The integrated demo is disabled on this deployment.", status=404)


def owned(db, ctx, ident, lock=False):
    enabled()
    query = select(Launch).where(Launch.id == str(ident), Launch.owner_user_id == ctx.user.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if not row:
        fail("NOT_FOUND", "Demo workspace not found.", status=404)
    if not ctx.user.active:
        fail("FORBIDDEN", "This account is inactive.", status=403)
    return row


def queue(db, ctx, row, code):
    command = Command(id=uid(), launch_id=row.id, step_code=code)
    job = Job(
        stage="DEMO_SETUP" if code == "SETUP" else "DEMO_STEP",
        input_fingerprint=digest({"command": command.id, "manifest": VERSION}),
        pipeline_version=VERSION,
        schema_version="IN_APP_DEMO_V1",
        configuration_hash=digest({"mode": "SIMULATION", "version": VERSION}),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=row.control_organization_id,
        request_json={"launch_id": row.id, "command_id": command.id, "step_code": code},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    command.job_id = job.id
    db.add(command)
    db.add(Outbox(job_id=job.id))
    row.active_command_id, row.status = command.id, "QUEUED"
    db.flush()


def launch(db, ctx, payload):
    enabled()
    previous = db.scalar(
        select(Launch)
        .where(Launch.owner_user_id == ctx.user.id)
        .order_by(Launch.created_at.desc(), Launch.id.desc())
        .limit(1)
    )
    if previous and previous.status in {"QUEUED", "RUNNING"}:
        return view(db, ctx, previous.id)
    if (
        previous
        and not payload.fresh
        and previous.manifest_version == VERSION
        and instant(db) < aware(previous.created_at) + FRESH_FOR
    ):
        return view(db, ctx, previous.id)
    org = Organization(legal_name="SIMULATION demo control", created_by=ctx.user.id)
    db.add(org)
    db.flush()
    row = Launch(
        owner_user_id=ctx.user.id,
        control_organization_id=org.id,
        manifest_version=VERSION,
        predecessor_id=previous.id if previous else None,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    queue(db, ctx, row, "SETUP")
    return view(db, ctx, row.id)


def step(db, ctx, ident, payload):
    row = owned(db, ctx, ident, True)
    if instant(db) >= aware(row.created_at) + FRESH_FOR:
        fail("DEMO_EVIDENCE_EXPIRED", "Demo evidence window elapsed. Start a fresh demo.")
    if row.status != "READY" or row.manifest_version != VERSION:
        fail("DEMO_NOT_READY", "Finish or replace this demo before requesting another step.")
    if row.next_step >= len(STEPS) or STEPS[row.next_step]["code"] != payload.step_code:
        fail("DEMO_STEP_ORDER", "Run the next registered simulation step.")
    queue(db, ctx, row, payload.step_code)
    return view(db, ctx, row.id)


def view(db, ctx, ident):
    row = owned(db, ctx, ident)
    fx = row.fixture_json or {}
    commands = list(
        db.scalars(
            select(Command)
            .where(Command.launch_id == row.id)
            .order_by(Command.created_at, Command.id)
        )
    )
    return {
        "schema_version": "IN_APP_DEMO_V1",
        "id": row.id,
        "status": row.status,
        "execution_mode": "SIMULATION",
        "manifest_version": row.manifest_version,
        "trade_id": row.trade_id,
        "organization_id": fx.get("organizations", {}).get("seller"),
        "consignment_id": fx.get("consignment_id"),
        "steps": STEPS,
        "next_step_index": row.next_step,
        "predecessor_id": row.predecessor_id,
        "expires_at": (aware(row.created_at) + FRESH_FOR).isoformat(),
        "expired": instant(db) >= aware(row.created_at) + FRESH_FOR,
        "route_study_ids": fx.get("route_study_ids", []),
        "sample_document_version_id": fx.get("sample_document_version_id"),
        "receipts": [
            {
                "id": c.id,
                "step_code": c.step_code,
                "status": c.status,
                "error_code": c.error_code,
                "result": c.receipt_json,
            }
            for c in commands
        ],
        "limitations": [
            "Fixtures, prices, approvals and movements are synthetic and labelled SIMULATION.",
            "Simulation actors run registered steps. Your production permissions are unchanged.",
            "Live routing is optional. The seeded comparison uses published simulation topology.",
            "Declared payment is not bank settlement; executable recovery is not implemented.",
        ],
    }


def job_access(db, job):
    enabled()
    owner = exists(db, User, job.requested_by_user_id)
    row = exists(db, Launch, job.request_json["launch_id"])
    command = exists(db, Command, job.request_json["command_id"])
    if not owner.active or owner.id != row.owner_user_id:
        fail("FORBIDDEN", "Demo owner access was revoked.", status=403)
    if (
        job.requested_by_organization_id != row.control_organization_id
        or command.launch_id != row.id
        or command.job_id != job.id
        or row.active_command_id != command.id
        or command.step_code != job.request_json["step_code"]
    ):
        fail("DEMO_CONTEXT_CHANGED", "This job does not own the active demo command.")
    return row, command


def fixture_access(db, user, org_id, trade):
    """The signed storage import can serve only a registered, active demo setup."""
    enabled()
    row = db.scalar(select(Launch).where(Launch.trade_id == trade.id))
    if not row or trade.execution_mode != "SIMULATION":
        fail("NOT_FOUND", "Registered simulation not found.", status=404)
    owner = exists(db, User, row.owner_user_id)
    command = db.get(Command, row.active_command_id)
    fx = row.fixture_json or {}
    if (
        not owner.active
        or not command
        or command.status != "RUNNING"
        or user.id not in fx.get("users", {}).values()
        or org_id not in fx.get("organizations", {}).values()
        or not user.identity_subject.startswith(f"operations-demo:phase4-appdemo-{row.id}:")
    ):
        fail("FORBIDDEN", "Simulation fixture context is not active.", status=403)
