"""Captured-input replay only, with explicit compatible-engine registration."""

from sqlalchemy import select

from app.trades.terms import digest

from . import calculation, privacy, rule_dependencies
from .clock import aware
from .models_computation import EvaluationExecution


def capture(db, evaluation):
    execution = db.scalar(
        select(EvaluationExecution).where(EvaluationExecution.evaluation_id == evaluation.id)
    )
    if not execution:
        return None, None
    retained = privacy.unseal(
        execution.encrypted_capture_json, execution.organisation_id, evaluation.id + ":calculation"
    )
    return execution, retained


def integrity(execution, retained):
    return bool(
        execution
        and digest(retained) == execution.capture_hash
        and digest(retained.get("result")) == execution.semantic_hash
    )


def recompute(db, evaluation):
    execution, retained = capture(db, evaluation)
    if not integrity(execution, retained):
        return "INCOMPLETE_INPUTS", []
    if execution.engine_manifest_json != rule_dependencies.engine_manifest():
        return "UNSUPPORTED_ENGINE", []
    try:
        result = calculation.calculate_full(
            retained["snapshot"], retained["rules"], aware(evaluation.evaluated_at)
        )
    except (KeyError, TypeError, ValueError):
        return "INCOMPLETE_INPUTS", []
    from app.product.replay import diff

    # Differences can contain private normalized invoice/provider values. Retain paths only.
    differences = [
        {
            "path": d["path"],
            "reason": "Captured compliance result differs; private values withheld.",
        }
        for d in diff(retained["result"], result)
    ]
    return ("MISMATCH" if differences else "MATCH"), differences
