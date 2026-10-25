"""Complete typed-expression traversal plus the registered input-provider dependency graph."""

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from platform import python_version

from app.trades.terms import digest

from . import calculation, expression, lineage

COMPILER_VERSION = "ABSENCE_AWARE_RULE_DEPS_V1"


@lru_cache(maxsize=1)
def engine_manifest():
    root = Path(__file__).resolve().parent
    files = [
        "calculation.py",
        "preparation.py",
        "inputs.py",
        "observations.py",
        "expression.py",
        "lineage.py",
        "rule_dependencies.py",
        "incremental.py",
        "scope_epochs.py",
        "context.py",
    ]
    return {
        "engine_version": expression.ENGINE_VERSION,
        "compiler_version": COMPILER_VERSION,
        "provider_version": "PH4_LINEAGE_V1",
        "python_version": python_version(),
        "code_hash": digest(
            {p: sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in files}
        ),
        "libraries": {name: version(name) for name in ("cryptography", "sqlalchemy")},
    }


def compile_rule(rule):
    definition = rule["definition"]
    paths = expression.dependencies(
        definition["applicability_expression"], definition["satisfaction_expression"]
    )
    if definition["date_basis"] == "INVOICE_DATE":
        paths = sorted(set([*paths, "invoice.issue_date"]))
    elif definition["date_basis"] == "PLANNED_ARRIVAL_TIME":
        paths = sorted(set([*paths, "facts.expected_arrival_at"]))
    providers, unknown = set(), []
    for path in paths:
        prefix, _, name = path.partition(".")
        if prefix == "proof" and name in lineage.PROVIDERS:
            providers.update(lineage.PROVIDERS[name])
        elif prefix in {"invoice", "facts", "inherited", "turnover"} and name:
            providers.add(prefix)
        elif path != "action":
            unknown.append(path)
    providers.update(lineage.DIAGNOSTICS.get(rule["requirement_code"], ()))
    if definition["date_basis"] == "OBSERVATION_TIME":
        providers.add("verification")
    return {
        "compiler_version": COMPILER_VERSION,
        "rule_id": rule["id"],
        "rule_hash": rule["hash"],
        "input_paths": paths,
        "providers": sorted(providers),
        "uncovered_paths": unknown,
        "reusable": not unknown,
        "temporal_conditions": {
            k: definition.get(k)
            for k in ("date_basis", "observation_check_type", "effective_from", "effective_until")
        },
        "applicability_and_coverage": "CURRENT_PACK_RESOLVED_AND_GLOBAL_GUARDS_ALWAYS_RECALCULATED",
    }


def resolve(rule, specification, snapshot, at, prepared=None):
    data = prepared if prepared is not None else calculation.prepared_data(snapshot)[0]
    witnesses = [
        {"kind": "RULE_REVISION", "id": rule["id"], "content_hash": rule["hash"]},
        {
            "kind": "RULE_PACK",
            "id": snapshot["pack"]["id"],
            "content_hash": snapshot["pack"]["hash"],
        },
        {"kind": "REGISTRY", "content_hash": digest(snapshot["registry"])},
        {"kind": "PROVIDER_VERSION", "version": snapshot["lineage"]["provider_version"]},
    ]
    ready = True
    for path in specification["input_paths"]:
        witnesses.append(
            {
                "kind": "INPUT_FIELD",
                "path": path,
                "content_hash": digest({"value": expression.get(data, path)}),
            }
        )
    for provider in specification["providers"]:
        values, current = lineage.witness(provider, snapshot)
        witnesses += values
        ready = ready and current
    diagnostic = data.get("diagnostics", {}).get(rule["requirement_code"], {})
    complete = specification["reusable"] and (
        not diagnostic or rule["requirement_code"] in lineage.DIAGNOSTICS
    )
    witnesses.append({"kind": "DIAGNOSTIC", "content_hash": digest(diagnostic)})
    if rule["definition"]["date_basis"] == "OBSERVATION_TIME":
        witnesses.append(
            {"kind": "OBSERVATION_TIMES", "content_hash": digest(snapshot["dimensions"])}
        )
    partition = {
        key: snapshot[key] for key in ("trade_id", "consignment_id", "action", "execution_mode")
    }
    value = {
        "partition": partition,
        "specification_hash": digest(specification),
        "witnesses": witnesses,
        "engine_manifest": engine_manifest(),
    }
    return {
        "dependency_digest": digest(value),
        "witnesses": deepcopy(witnesses),
        "complete": bool(complete),
        "allow_lookup": ready,
        "partition": partition,
    }
