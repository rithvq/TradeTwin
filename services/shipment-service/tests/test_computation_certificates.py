"""Exercise certificate validation directly, independently of database immutability guards."""

import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import calculation, incremental, rule_dependencies  # noqa: E402
from app.trades.terms import digest  # noqa: E402


class WitnessStore:
    def __init__(self, witnesses):
        self.witnesses = witnesses

    def scalars(self, _statement):
        return iter(self.witnesses)


@pytest.fixture()
def certificate():
    start = datetime(2026, 10, 26, tzinfo=UTC)
    partition = {
        "trade_id": "trade-a",
        "consignment_id": "consignment-a",
        "action": "PICKUP_CONFIRMED",
        "execution_mode": "SIMULATION",
    }
    values = [
        {"kind": "INPUT_FIELD", "path": "invoice.issue_date", "content_hash": "invoice-hash"},
        {"kind": "SCOPE_EPOCH", "scope_key": "trade:trade-a:FACTS", "epoch": 3},
    ]
    spec = SimpleNamespace(
        id="spec-a",
        specification_json={"rule_id": "rule-a", "compiler_version": "certificate-test"},
    )
    spec.content_hash = digest(spec.specification_json)
    basis = {
        "complete": True,
        "partition": partition,
        "dependency_digest": "dependency-hash",
        "witnesses": deepcopy(values),
    }
    row = SimpleNamespace(
        id="computation-a",
        **partition,
        rule_id="rule-a",
        specification_id=spec.id,
        engine_manifest_hash="engine-hash",
        dependency_digest=basis["dependency_digest"],
        result_json={"outcome": "SATISFIED", "predicate_result": True},
        supporting_references_json=[],
        reusable=True,
        valid_from=start,
        valid_until=start + timedelta(minutes=10),
    )
    row.content_hash = digest(
        incremental.integrity_basis(row, spec.content_hash, sorted(values, key=digest))
    )
    # Deliberately reverse storage order: integrity uses canonical witness collections.
    store = WitnessStore(
        [SimpleNamespace(witness_json=value, content_hash=digest(value)) for value in values[::-1]]
    )
    return store, row, basis, spec, start


def validate(certificate, *, at=None, manifest="engine-hash"):
    store, row, basis, spec, start = certificate
    return incremental.validate_reuse(store, row, basis, spec, manifest, at or start)


@pytest.mark.parametrize("field", ["specification_json", "content_hash"])
def test_specification_integrity_rejects_altered_body_or_hash(certificate, field):
    assert validate(certificate) is None
    spec = certificate[3]
    if field == "specification_json":
        spec.specification_json["compiler_version"] = "changed"
    else:
        spec.content_hash = "changed"
    assert validate(certificate) == "SPECIFICATION_INTEGRITY_FAILED"


@pytest.mark.parametrize("alteration", ["value", "hash", "missing", "additional"])
def test_witness_integrity_rejects_changed_collection_or_hash(certificate, alteration):
    assert validate(certificate) is None
    store = certificate[0]
    if alteration == "value":
        store.witnesses[0].witness_json["epoch"] += 1
        # Even a self-consistent hash cannot replace the current expected witness.
        store.witnesses[0].content_hash = digest(store.witnesses[0].witness_json)
    elif alteration == "hash":
        store.witnesses[0].content_hash = "changed"
    elif alteration == "missing":
        store.witnesses.pop()
    else:
        store.witnesses.append(deepcopy(store.witnesses[0]))
    assert validate(certificate) == "WITNESS_INTEGRITY_FAILED"


@pytest.mark.parametrize("field", ["result_json", "supporting_references_json", "valid_until"])
def test_computation_integrity_covers_result_references_and_interval(certificate, field):
    assert validate(certificate) is None
    row = certificate[1]
    if field == "result_json":
        row.result_json["outcome"] = "FAILED"
    elif field == "supporting_references_json":
        row.supporting_references_json.append({"kind": "unrecorded-reference"})
    else:
        row.valid_until += timedelta(seconds=1)
    assert validate(certificate) == "COMPUTATION_INTEGRITY_FAILED"


@pytest.mark.parametrize("field", ["trade_id", "consignment_id", "action", "execution_mode"])
def test_current_partition_must_match_saved_computation(certificate, field):
    assert validate(certificate) is None
    certificate[2]["partition"][field] = "different"
    assert validate(certificate) == "PARTITION_CHANGED"


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("specification_id", "ENGINE_OR_RULE_CHANGED"),
        ("engine_manifest_hash", "ENGINE_OR_RULE_CHANGED"),
        ("dependency_digest", "DEPENDENCY_CHANGED"),
    ],
)
def test_current_rule_engine_and_dependencies_must_match(certificate, field, expected):
    assert validate(certificate) is None
    setattr(certificate[1], field, "different")
    assert validate(certificate) == expected


@pytest.mark.parametrize("saved_reusable", [False, True])
def test_incomplete_coverage_cannot_be_reused(certificate, saved_reusable):
    assert validate(certificate) is None
    certificate[1].reusable = saved_reusable
    certificate[2]["complete"] = not saved_reusable
    assert validate(certificate) == "DEPENDENCY_COVERAGE_INCOMPLETE"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(microseconds=-1), "VALIDITY_BOUNDARY_REACHED"),
        (timedelta(), None),
        (timedelta(minutes=10, microseconds=-1), None),
        (timedelta(minutes=10), "VALIDITY_BOUNDARY_REACHED"),
    ],
)
def test_certificate_interval_includes_start_and_excludes_end(certificate, offset, expected):
    assert validate(certificate, at=certificate[4] + offset) == expected


def temporal_rule(date_basis, start, end):
    return {
        "id": "temporal-rule",
        "hash": "temporal-rule-hash",
        "requirement_code": "TEMPORAL_TEST",
        "definition": {
            "requirement_code": "TEMPORAL_TEST",
            "date_basis": date_basis,
            "effective_from": start.isoformat(),
            "effective_until": end.isoformat(),
            "observation_check_type": "IRN_LIVE_STATUS",
            "applicability_expression": {"op": "literal", "value": True},
            "satisfaction_expression": {"op": "literal", "value": True},
        },
    }


@pytest.mark.parametrize(
    "date_basis", ["ACTION_TIME", "INVOICE_DATE", "PLANNED_ARRIVAL_TIME", "OBSERVATION_TIME"]
)
@pytest.mark.parametrize("position", ["BEFORE_START", "START", "BEFORE_END", "END"])
def test_each_date_basis_obeys_rule_effectivity_boundaries(date_basis, position):
    start = datetime(2026, 10, 26, tzinfo=ZoneInfo("Asia/Kolkata"))
    end = start + timedelta(days=2)
    # Invoice dates have day granularity; all other bases exercise microsecond edges.
    step = timedelta(days=1) if date_basis == "INVOICE_DATE" else timedelta(microseconds=1)
    point = {
        "BEFORE_START": start - step,
        "START": start,
        "BEFORE_END": end - step,
        "END": end,
    }[position]
    data = {
        "invoice": {"issue_date": point.date().isoformat()},
        "facts": {"expected_arrival_at": point.isoformat()},
    }
    dimensions = [
        {
            "selected": True,
            "check_type": "IRN_LIVE_STATUS",
            "provider_observed_at": point.isoformat(),
            "checked_at": (end + timedelta(days=1)).isoformat(),
        }
    ]
    at = point if date_basis == "ACTION_TIME" else start + timedelta(hours=1)
    rule = temporal_rule(date_basis, start, end)
    assert calculation.rule_time(rule["definition"], data, dimensions, at)[0] == point
    kernel = calculation.calculate_rule(rule, data, dimensions, at)
    active = position in {"START", "BEFORE_END"}
    assert kernel["applicability"] == ("APPLICABLE" if active else "NOT_APPLICABLE")
    assert kernel["outcome"] == ("SATISFIED" if active else "NOT_APPLICABLE")


@pytest.mark.parametrize(
    ("date_basis", "paths", "providers"),
    [
        ("ACTION_TIME", [], []),
        ("INVOICE_DATE", ["invoice.issue_date"], ["invoice"]),
        ("PLANNED_ARRIVAL_TIME", ["facts.expected_arrival_at"], ["facts"]),
        ("OBSERVATION_TIME", [], ["verification"]),
    ],
)
def test_compiler_adds_dependencies_for_implicit_date_bases(date_basis, paths, providers):
    start = datetime(2026, 10, 26, tzinfo=UTC)
    rule = temporal_rule(date_basis, start, start + timedelta(days=2))
    specification = rule_dependencies.compile_rule(rule)
    assert specification["reusable"]
    assert specification["input_paths"] == paths
    assert specification["providers"] == providers
    assert specification["temporal_conditions"] == {
        key: rule["definition"][key]
        for key in ("date_basis", "observation_check_type", "effective_from", "effective_until")
    }
