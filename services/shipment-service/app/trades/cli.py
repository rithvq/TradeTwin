"""Explicit seed command. Only disposable databases may be reset by test harnesses."""

import argparse
import json

from app.database import SessionLocal, engine

from .demo import seed_demo
from .migrate import migrate


def main():
    parser = argparse.ArgumentParser(
        description="Seed commercial agreement demo fixtures (no login bypass)"
    )
    parser.add_argument(
        "--identity-map", help="JSON mapping five demo role names to existing OAuth profile IDs"
    )
    args = parser.parse_args()
    subjects = json.loads(args.identity_map) if args.identity_map else None
    if subjects and len(set(subjects.values())) != len(subjects):
        raise SystemExit("Use distinct identities for the separate demonstration roles")
    migrate(engine)
    with SessionLocal() as db:
        print(json.dumps(seed_demo(db, subjects), indent=2))


if __name__ == "__main__":
    main()
