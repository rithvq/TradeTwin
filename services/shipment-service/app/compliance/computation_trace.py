"""Recipient-authorized calculation explanations; never expose source witnesses or captures."""

from sqlalchemy import select

from . import evaluations
from .models import Rule
from .models_computation import EvaluationComputationLink, EvaluationExecution


def read(db, ctx, ident):
    evaluation, _, _, _ = evaluations.exact(db, ctx, ident)
    execution = db.scalar(
        select(EvaluationExecution).where(EvaluationExecution.evaluation_id == ident)
    )
    if not execution:
        return {
            "evaluation_id": evaluation.id,
            "status": "NOT_RECORDED",
            "strategy": None,
            "authoritative_strategy": None,
            "rules_total": 0,
            "rules_recomputed": 0,
            "rules_reused": 0,
            "shadow_rules_reused": 0,
            "shadow_equivalent": None,
            "invalidation_reasons": [],
            "rules": [],
            "permission_reused": False,
            "notice": "No computation trace was retained for this evaluation.",
        }
    trace = execution.trace_json
    return {
        "evaluation_id": evaluation.id,
        "status": "RECORDED",
        **{
            key: trace[key]
            for key in (
                "strategy",
                "authoritative_strategy",
                "rules_total",
                "rules_recomputed",
                "rules_reused",
                "shadow_rules_reused",
                "shadow_equivalent",
                "invalidation_reasons",
                "permission_reused",
            )
        },
        "rules": [
            {
                "rule_code": rule.rule_code,
                "disposition": link.disposition,
                "reason_codes": link.reason_codes_json,
            }
            for link, rule in db.execute(
                select(EvaluationComputationLink, Rule)
                .join(Rule, Rule.id == EvaluationComputationLink.rule_id)
                .where(EvaluationComputationLink.evaluation_id == ident)
                .order_by(Rule.rule_code)
            )
        ],
        "notice": "Calculation reuse carries no release approval, packet, driver acknowledgment "
        "or dispatch authorisation. The new evaluation requires its own release workflow.",
    }
