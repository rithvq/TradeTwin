"""Phase 2 browser-only simulated gate fixture; refuses non-disposable databases."""

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/shipment-service"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("consignment_id")
    parser.add_argument("action", choices=["PICKUP_CONFIRMED", "DEPARTED"])
    args = parser.parse_args()
    url = make_url(os.environ["DATABASE_URL"])
    folder = Path(os.environ["OPERATIONS_BROWSER_DATABASE_ROOT"]).resolve()
    if (
        url.get_backend_name() != "sqlite"
        or Path(url.database).resolve() != folder / "shipment.db"
        or not folder.name.startswith("tradetwin-operations-")
    ):
        raise SystemExit(
            "Metadata-only fixture requires the disposable operations-browser database"
        )
    from app.compliance import context, demo
    from app.database import SessionLocal
    from app.operations.models import Consignment
    from app.trades.router import router  # noqa: F401

    fx = json.loads(sys.stdin.read())
    with SessionLocal() as db:
        cn = db.get(Consignment, args.consignment_id)
        if not cn or cn.trade_id != fx["trade_id"]:
            raise SystemExit("Test consignment not found in this disposable fixture")
        head = context.heads(db, cn)
        if not head or not head.current_binding_revision_id:
            demo.prepare(db, fx, cn.id)
        token = demo.authorise(db, fx, cn.id, args.action)
        db.commit()
    print(json.dumps({"authorisation_id": token["id"], "mode": "SIMULATION"}))


if __name__ == "__main__":
    main()
