"""Seed an isolated fixture and use the real durable worker to compute its baseline."""

import argparse
import json
from pathlib import Path

from app.database import SessionLocal, engine
from app.document_desk.worker import run_one
from app.trades.migrate import migrate

from .demo import refresh_phase4, seed
from .models import Run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="phase4-freight")
    parser.add_argument("--refresh-fixture", type=Path)
    args = parser.parse_args()
    migrate(engine)
    if args.refresh_fixture:
        from app.compliance import demo as release_demo

        fx = json.loads(args.refresh_fixture.read_text(encoding="utf-8"))
        with SessionLocal() as db:
            refresh_phase4(db, fx, fx["consignment_id"])
            token = release_demo.authorise(db, fx, fx["consignment_id"], "PICKUP_CONFIRMED")
            db.commit()
        print(json.dumps({"authorisation_id": token["id"]}))
        return
    fx = seed(SessionLocal, args.namespace)
    with SessionLocal() as db:
        job = db.get(Run, fx["run_id"]).job_id
    if not run_one(SessionLocal, job):
        raise SystemExit("Baseline worker did not complete")
    print(json.dumps(fx, indent=2))


if __name__ == "__main__":
    main()
