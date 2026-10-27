from sqlalchemy import select

from app.operations.access import exists, fail
from app.trades.models import Trade, User

from .catalog import STAGES  # noqa: F401
from .models import Command, Launch
from .service import job_access


def lock(db, job):
    db.scalar(select(User).where(User.id == job.requested_by_user_id).with_for_update())


def process(sessions, lease):
    from app.document_desk.jobs import leased

    from .scenario import execute, install

    with sessions() as db:
        job, _ = leased(db, *lease, lock=False)
        row, command = job_access(db, job)
        ident, code = row.id, command.step_code
    return (
        install(sessions, ident, lease)
        if code == "SETUP"
        else execute(sessions, ident, code, lease)
    )


def complete(db, job, output):
    row, command = job_access(db, job)
    if command.status == "COMPLETED":
        return
    trade = exists(db, Trade, row.trade_id)
    if trade.execution_mode != "SIMULATION":
        fail("MODE_MISMATCH", "Demo commands cannot publish production data.")
    command.receipt_json, command.status = output, "COMPLETED"
    row.status = "READY"
    if command.step_code != "SETUP":
        row.next_step += 1


def mark(db, job, status):
    command = db.get(Command, job.request_json["command_id"])
    row = db.get(Launch, job.request_json["launch_id"])
    if command and command.status != "COMPLETED":
        command.status, row.status = status, status
        command.error_code = job.last_error_code if status == "FAILED" else None
