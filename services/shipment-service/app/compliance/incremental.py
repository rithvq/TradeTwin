"""Consignment-local, integrity-checked kernel reuse. No review or permission is cached."""

import os
from copy import deepcopy
from time import perf_counter_ns, process_time_ns

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.operations.access import fail
from app.trades.models import uid
from app.trades.terms import digest

from . import calculation, privacy, rule_dependencies
from .clock import aware
from .models import Requirement
from .models_computation import (
    DependencyWitness,
    EvaluationComputationLink,
    EvaluationExecution,
    RuleComputation,
    RuleDependencySpecification,
)


def mode():
    value = os.getenv("COMPLIANCE_EVALUATION_MODE", "FULL").upper()
    if value not in {"FULL", "SHADOW", "INCREMENTAL"}:
        fail("EVALUATION_MODE_INVALID", "Use a registered server evaluation mode.", status=503)
    return value


def integrity_basis(row, specification_hash, witnesses):
    return {
        "trade_id": row.trade_id,
        "consignment_id": row.consignment_id,
        "action": row.action,
        "execution_mode": row.execution_mode,
        "rule_id": row.rule_id,
        "specification_hash": specification_hash,
        "engine_manifest_hash": row.engine_manifest_hash,
        "dependency_digest": row.dependency_digest,
        "result": row.result_json,
        "references": row.supporting_references_json,
        "witnesses": witnesses,
        "reusable": row.reusable,
        "valid_from": aware(row.valid_from).isoformat(),
        "valid_until": aware(row.valid_until).isoformat(),
    }


def validate_reuse(db, row, basis, spec, manifest_hash, at):
    if digest(spec.specification_json) != spec.content_hash:
        return "SPECIFICATION_INTEGRITY_FAILED"
    if not row.reusable or not basis["complete"]:
        return "DEPENDENCY_COVERAGE_INCOMPLETE"
    if any(getattr(row, key) != value for key, value in basis["partition"].items()):
        return "PARTITION_CHANGED"
    if row.specification_id != spec.id or row.engine_manifest_hash != manifest_hash:
        return "ENGINE_OR_RULE_CHANGED"
    if row.dependency_digest != basis["dependency_digest"]:
        return "DEPENDENCY_CHANGED"
    if not aware(row.valid_from) <= at < aware(row.valid_until):
        return "VALIDITY_BOUNDARY_REACHED"
    witnesses = list(
        db.scalars(
            select(DependencyWitness)
            .where(DependencyWitness.computation_id == row.id)
            .order_by(DependencyWitness.id)
        )
    )
    # Witness IDs are random; compare canonical collections, not insertion/UUID order.
    values = sorted([w.witness_json for w in witnesses], key=digest)
    expected = sorted(basis["witnesses"], key=digest)
    if values != expected or any(digest(w.witness_json) != w.content_hash for w in witnesses):
        return "WITNESS_INTEGRITY_FAILED"
    if digest(integrity_basis(row, spec.content_hash, values)) != row.content_hash:
        return "COMPUTATION_INTEGRITY_FAILED"
    return None


def reasons(db, previous, basis, snapshot, at):
    if not basis["complete"]:
        return ["DEPENDENCY_COVERAGE_INCOMPLETE"]
    if not basis["allow_lookup"]:
        return ["MISSING_SCOPE_RECORD"]
    if previous is None:
        return ["NO_COMPATIBLE_COMPUTATION"]
    if not aware(previous.valid_from) <= at < aware(previous.valid_until):
        return ["VALIDITY_BOUNDARY_REACHED"]
    old = {
        w.witness_json.get("scope_key"): w.witness_json
        for w in db.scalars(
            select(DependencyWitness).where(DependencyWitness.computation_id == previous.id)
        )
        if w.witness_json["kind"] == "SCOPE_EPOCH"
    }
    codes = {
        snapshot["lineage"]["epochs"][w["scope_key"]]["last_change_code"]
        for w in basis["witnesses"]
        if w["kind"] == "SCOPE_EPOCH" and old.get(w["scope_key"]) != w
    }
    return sorted(codes) or ["DEPENDENCY_CHANGED"]


def specification_record(db, ctx, rule, specification, manifest_hash):
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(RuleDependencySpecification)
        .values(
            id=uid(),
            rule_id=rule["id"],
            compiler_hash=manifest_hash,
            specification_json=specification,
            content_hash=digest(specification),
            reusable=specification["reusable"],
            created_by_user_id=ctx.user.id,
        )
        .on_conflict_do_nothing(index_elements=["rule_id", "compiler_hash"])
    )
    return db.scalar(
        select(RuleDependencySpecification).where(
            RuleDependencySpecification.rule_id == rule["id"],
            RuleDependencySpecification.compiler_hash == manifest_hash,
        )
    )


def execute(db, ctx, row, snapshot, rules, at):
    selected = mode()
    started, cpu_started = perf_counter_ns(), process_time_ns()
    manifest = rule_dependencies.engine_manifest()
    manifest_hash = digest(manifest)
    reference = (
        calculation.calculate_full(snapshot, rules, at) if selected in {"FULL", "SHADOW"} else None
    )
    data = calculation.prepared_data(snapshot)[0]
    planned, kernels = [], {}
    candidates_used = 0
    for rule in rules:
        specification = rule_dependencies.compile_rule(rule)
        spec = db.scalar(
            select(RuleDependencySpecification).where(
                RuleDependencySpecification.rule_id == rule["id"],
                RuleDependencySpecification.compiler_hash == manifest_hash,
            )
        )
        if not spec:
            spec = specification_record(db, ctx, rule, specification, manifest_hash)
        basis = rule_dependencies.resolve(rule, specification, snapshot, at, prepared=data)
        prior_query = (
            select(RuleComputation)
            .where(
                RuleComputation.trade_id == row.trade_id,
                RuleComputation.consignment_id == row.consignment_id,
                RuleComputation.action == row.action,
                RuleComputation.execution_mode == row.execution_mode,
                RuleComputation.rule_id == rule["id"],
                RuleComputation.engine_manifest_hash == manifest_hash,
            )
            .order_by(RuleComputation.created_at.desc(), RuleComputation.id.desc())
        )
        prior = None
        codes = ["FULL_REFERENCE"] if selected == "FULL" else []
        if selected != "FULL":
            prior = (
                db.scalar(
                    prior_query.where(
                        RuleComputation.dependency_digest == basis["dependency_digest"],
                        RuleComputation.reusable.is_(True),
                        RuleComputation.valid_from <= at,
                        RuleComputation.valid_until > at,
                    ).limit(1)
                )
                if basis["complete"] and basis["allow_lookup"]
                else None
            )
            problem = validate_reuse(db, prior, basis, spec, manifest_hash, at) if prior else None
            if prior and not problem:
                kernels[rule["id"]] = deepcopy(prior.result_json)
                candidates_used += 1
                codes = ["UNCHANGED_COMPLETE_DEPENDENCIES"]
            else:
                latest = db.scalar(prior_query.limit(1))
                codes = [problem] if problem else reasons(db, latest, basis, snapshot, at)
                prior = None
        if prior is None:
            kernels[rule["id"]] = (
                deepcopy(reference["kernels"][rule["id"]])
                if selected == "FULL"
                else calculation.calculate_rule(rule, data, snapshot["dimensions"], at)
            )
        planned.append(
            {"rule": rule, "spec": spec, "basis": basis, "previous": prior, "reasons": codes}
        )
    candidate = (
        calculation.calculate_full(snapshot, rules, at, kernels=kernels)
        if selected != "FULL"
        else reference
    )
    equivalent = reference == candidate if selected == "SHADOW" else None
    result = reference if selected in {"FULL", "SHADOW"} else candidate
    authority = "FULL" if selected in {"FULL", "SHADOW"} else "INCREMENTAL"
    trace = {
        "schema": "COMPLIANCE_COMPUTATION_TRACE_V1",
        "strategy": selected,
        "authoritative_strategy": authority,
        "rules_total": len(rules),
        "rules_reused": candidates_used if selected == "INCREMENTAL" else 0,
        "rules_recomputed": len(rules) - candidates_used
        if selected == "INCREMENTAL"
        else len(rules),
        "shadow_rules_reused": candidates_used if selected == "SHADOW" else 0,
        "shadow_equivalent": equivalent,
        "rule_executions": len(rules)
        if selected == "FULL"
        else (2 * len(rules) - candidates_used)
        if selected == "SHADOW"
        else len(rules) - candidates_used,
        "calculation_wall_ns": perf_counter_ns() - started,
        "calculation_cpu_ns": process_time_ns() - cpu_started,
        "invalidation_reasons": sorted(
            {
                code
                for item in planned
                for code in item["reasons"]
                if code != "UNCHANGED_COMPLETE_DEPENDENCIES"
            }
        ),
        "permission_reused": False,
        "release_approval_carried_forward": False,
        "current_authorisation": "NOT_CREATED_BY_CALCULATION_REUSE",
    }
    if selected == "SHADOW" and not equivalent:
        trace["invalidation_reasons"].append("SHADOW_MISMATCH")
    return result, {
        "snapshot": snapshot,
        "rules": rules,
        "result": result,
        "planned": planned,
        "trace": trace,
        "manifest": manifest,
        "manifest_hash": manifest_hash,
    }


def retain(db, ctx, evaluation, bundle, at):
    from .evidence_changes import retain as retain_change_baseline

    retain_change_baseline(db, ctx, evaluation, bundle)
    requirements = {
        r.rule_id: r
        for r in db.scalars(select(Requirement).where(Requirement.evaluation_id == evaluation.id))
    }
    result, trace = bundle["result"], bundle["trace"]
    for item in bundle["planned"]:
        rule, basis, spec = item["rule"], item["basis"], item["spec"]
        previous = item["previous"] if trace["authoritative_strategy"] == "INCREMENTAL" else None
        computation = previous
        if computation is None:
            computation = RuleComputation(
                trade_id=evaluation.trade_id,
                consignment_id=evaluation.consignment_id,
                origin_evaluation_id=evaluation.id,
                rule_id=rule["id"],
                specification_id=spec.id,
                action=evaluation.action,
                execution_mode=evaluation.execution_mode,
                engine_manifest_hash=bundle["manifest_hash"],
                dependency_digest=basis["dependency_digest"],
                result_json=deepcopy(result["kernels"][rule["id"]]),
                supporting_references_json=[],
                reusable=basis["complete"],
                valid_from=at,
                valid_until=calculation.timestamp(result["valid_until"]),
                created_by_user_id=ctx.user.id,
            )
            values = sorted(basis["witnesses"], key=digest)
            computation.supporting_references_json = [
                {"kind": w["kind"], **({"scope_key": w["scope_key"]} if "scope_key" in w else {})}
                for w in values
            ]
            computation.content_hash = digest(
                integrity_basis(computation, spec.content_hash, values)
            )
            db.add(computation)
            db.flush()
            for witness in values:
                db.add(
                    DependencyWitness(
                        computation_id=computation.id,
                        witness_json=witness,
                        content_hash=digest(witness),
                        created_by_user_id=ctx.user.id,
                    )
                )
        db.add(
            EvaluationComputationLink(
                evaluation_id=evaluation.id,
                requirement_id=requirements[rule["id"]].id,
                rule_id=rule["id"],
                computation_id=computation.id,
                disposition="REUSED" if previous else "RECOMPUTED",
                reason_codes_json=item["reasons"]
                if trace["strategy"] != "SHADOW"
                else ["SHADOW_FULL_AUTHORITATIVE"],
                created_by_user_id=ctx.user.id,
            )
        )
    captured = {"snapshot": bundle["snapshot"], "rules": bundle["rules"], "result": result}
    db.add(
        EvaluationExecution(
            evaluation_id=evaluation.id,
            organisation_id=ctx.org_id,
            requested_strategy=trace["strategy"],
            authoritative_strategy=trace["authoritative_strategy"],
            engine_manifest_json=bundle["manifest"],
            encrypted_capture_json=privacy.seal(
                captured, ctx.org_id, evaluation.id + ":calculation"
            ),
            capture_hash=digest(captured),
            semantic_hash=digest(result),
            trace_json=trace,
            created_by_user_id=ctx.user.id,
        )
    )
