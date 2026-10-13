"""Indexed immutable calculation facets retain the same canonical result as the run."""

from sqlalchemy import inspect

from app.trades.terms import digest

from .models import (
    ConstraintResult,
    CostItem,
    GraphEdge,
    GraphNode,
    Ranking,
    ResourceVersion,
    ScenarioResult,
    SelectionEvent,
)
from .routing import aware_from


def graph_rows(db, dataset):
    for node in dataset.dataset_json["nodes"]:
        db.add(GraphNode(dataset_revision_id=dataset.id, **node))
    db.flush()
    for edge in dataset.dataset_json["edges"]:
        db.add(
            GraphEdge(
                dataset_revision_id=dataset.id,
                edge_key=edge["edge_key"],
                from_node_key=edge["from_node_key"],
                to_node_key=edge["to_node_key"],
                distance_meters=edge["distance_meters"],
                estimated_driving_seconds=edge["estimated_driving_seconds"],
                edge_json=edge,
            )
        )


def result_rows(db, candidates, rankings, run_id):
    db.flush()
    for candidate in candidates:
        for scenario, value in candidate["scenarios"].items():
            total = value["cost"]["comparison_total_minor"]
            db.add(
                ScenarioResult(
                    candidate_id=candidate["candidate_id"],
                    scenario_code=scenario,
                    estimated_departure_at=aware_from(value["estimated_departure_at"]),
                    estimated_arrival_at=aware_from(value["estimated_arrival_at"]),
                    comparison_total_minor=int(total) if total is not None else None,
                    result_json=value,
                    content_hash=digest(value),
                )
            )
            for constraint in [
                *value["planning_constraint_results"],
                *value["candidate_compliance_results"],
            ]:
                db.add(
                    ConstraintResult(
                        candidate_id=candidate["candidate_id"],
                        category=constraint["category"],
                        requirement_code=constraint.get(
                            "requirement_code", constraint.get("rule_code")
                        ),
                        outcome=constraint["outcome"],
                        result_json=constraint,
                    )
                )
            for component in value["cost"]["calculation_steps"]:
                db.add(
                    CostItem(
                        candidate_id=candidate["candidate_id"],
                        scenario_code=scenario,
                        component_code=component["component_code"],
                        origin=component["origin"],
                        amount_minor=int(component["amount_minor"])
                        if component["amount_minor"] is not None
                        else None,
                        calculation_json=component,
                    )
                )
    for scenario, objectives in rankings.items():
        for objective, values in objectives.items():
            for value in values:
                db.add(
                    Ranking(
                        run_id=run_id,
                        candidate_id=value["candidate_id"],
                        scenario_code=scenario,
                        objective=objective,
                        rank=value["rank"],
                        pareto_member=value["pareto_member"],
                        score_numerator=value["score_numerator"],
                        score_denominator=value["score_denominator"],
                        ranking_json=value,
                    )
                )


def selection_event(db, ctx, selection, code, head):
    db.add(
        SelectionEvent(
            proposal_id=selection.id,
            event_type=code,
            event_json={
                "proposal_hash": selection.content_hash,
                "lifecycle": head.lifecycle_projection,
                "assignment_id": head.proposed_assignment_id,
                "commitment_id": head.current_commitment_id,
            },
            actor_user_id=ctx.user.id,
        )
    )


def resource_changed(db, mode, kind, ident):
    if not inspect(db.get_bind()).has_table(ResourceVersion.__tablename__):
        return
    key = (mode, kind, ident)
    row = db.get(ResourceVersion, key)
    if row:
        row.version += 1
    else:
        db.add(
            ResourceVersion(execution_mode=mode, resource_type=kind, resource_id=ident, version=1)
        )
