"""Opt-in real-provider check with public synthetic gates; never prints credentials or documents."""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/shipment-service"))

from app.freight_routes.engine import evaluate  # noqa: E402
from app.freight_routes.schemas import Weights  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    departure = datetime.now(UTC) + timedelta(hours=1)
    snapshot = {
        "truck": {
            "height_m": "3.7",
            "width_m": "2.45",
            "length_m": "9",
            "tare_kg": "6500",
            "axle_load_kg": "6000",
        },
        "cargo_weight_kg": "400",
        "hazardous_declared": False,
        "pickup": {"coordinates": [77.5946, 12.9716], "state_code": "29"},
        "drop": {"coordinates": [80.2707, 13.0827], "state_code": "33"},
        "corridor": {
            "events": [],
            "policies": [],
            "coverage": {"status": "NOT_CONFIGURED", "missing_scopes": [], "checked_sources": []},
        },
        "request": {
            "source_mode": "LIVE",
            "departure_at": departure.isoformat(),
            "weights": Weights().model_dump(),
            "include_weather": True,
            "planned_stop_seconds": 1800,
        },
        "policy": {"sources": [], "packs": [], "supported_corridors": []},
        "history": [],
        "permit_coverage": {"covered_states": [], "valid_until": None},
        "execution_mode": "SIMULATION",
    }
    try:
        result = evaluate(snapshot)
    except TradeError as error:
        print(json.dumps({"status": "UNAVAILABLE", "code": error.code}))
        raise SystemExit(1) from None
    public = {
        "checked_at": result["checked_at"],
        "synthetic_public_gates": "Bengaluru to Chennai",
        "candidate_count": len(result["candidates"]),
        "comparison_status": result["comparison"]["comparison_status"],
        "provider_failures": result["provider_failures"],
        "candidates": [
            {
                "label": r["label"],
                "distance_m": r["distance_m"],
                "driving_seconds": r["driving_seconds"],
                "state_sequence": r["corridor"]["state_sequence"],
                "boundary_reference": r["corridor"]["boundaries"],
                "weather_status": r["weather"]["status"],
                "reason_codes": r["reason_codes"],
            }
            for r in result["candidates"]
        ],
    }
    folder = ROOT / "artifacts/audit/freight-routes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "live-check.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(public))


if __name__ == "__main__":
    main()
