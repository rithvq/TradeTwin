"""Registered pure captured-input solver shared by business jobs and read-only replay."""

from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.trades.terms import digest

from .assessment import assess
from .calculator import ENGINE_VERSION, rank


def engine_manifest():
    root = Path(__file__).resolve().parents[1]
    files = [
        "freight/compute.py",
        "freight/calculator.py",
        "freight/assessment.py",
        "freight/routing.py",
        "corridor/impact.py",
        "corridor/geometry.py",
    ]
    return {
        "engine_version": ENGINE_VERSION,
        "code_hash": digest(
            {p: sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in files}
        ),
        "dependencies": {p: version(p) for p in ["networkx", "shapely"]},
    }


def candidate(snapshot, source, input_hash, execution_mode):
    ident = str(uuid5(NAMESPACE_URL, input_hash + ":" + source["quote_revision_id"]))
    scenarios = {
        s["scenario_code"]: assess(snapshot, source, s, ident) for s in snapshot["scenarios"]
    }
    value = {
        "candidate_id": ident,
        "offer_label": source["quote"].get("carrier_offer_reference")
        or source["quote_revision_id"][:8],
        "quote_revision_id": source["quote_revision_id"],
        "quote_hash": source["quote_hash"],
        "route_template_revision_id": source["quote"]["route_template_revision_id"],
        "carrier_organisation_id": source["quote"]["carrier_organisation_id"],
        "vehicle_id": source["quote"]["vehicle_id"],
        "scenarios": scenarios,
        "execution_mode": execution_mode,
    }
    return {**value, "candidate_hash": digest(value)}


def captured_result(snapshot, input_hash, execution_mode):
    candidates = [candidate(snapshot, s, input_hash, execution_mode) for s in snapshot["sources"]]
    rankings = {
        s["scenario_code"]: {
            objective: rank(candidates, s["scenario_code"], objective, snapshot["balanced_weights"])
            for objective in ["LOWEST_COMPARABLE_COST", "EARLIEST_ESTIMATED_ARRIVAL", "BALANCED"]
        }
        for s in snapshot["scenarios"]
    }
    return {"candidates": candidates, "rankings": rankings}
