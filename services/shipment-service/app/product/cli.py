"""Run an already-authorised product job through the normal durable worker."""

import argparse
from uuid import UUID

from app.database import SessionLocal, engine
from app.document_desk.models import Job
from app.document_desk.worker import run_one
from app.trades.migrate import migrate

from .jobs import STAGES
from .models import ReplayRequest


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-id", type=UUID)
    target.add_argument("--replay-request-id", type=UUID)
    args = parser.parse_args()
    migrate(engine)
    with SessionLocal() as db:
        requested = (
            db.get(ReplayRequest, str(args.replay_request_id)) if args.replay_request_id else None
        )
        ident = requested.job_id if requested else str(args.job_id) if args.job_id else None
        job = db.get(Job, ident) if ident else None
        if not job or job.stage not in STAGES:
            raise SystemExit("No registered product job found")
    if not run_one(SessionLocal, ident):
        raise SystemExit("Product job was not claimable")
    with SessionLocal() as db:
        if db.get(Job, ident).status != "SUCCEEDED":
            raise SystemExit("Product job did not succeed; inspect its authorised status endpoint")
    print("Product job completed through its normal leased worker.")


if __name__ == "__main__":
    main()
