"""Full-reference equivalence, negative dependencies, temporal bounds and permission separation."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from time import perf_counter_ns, process_time_ns

import pytest
from sqlalchemy import create_engine, delete, event, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import (  # noqa: E402
    calculation,
    calculation_replay,
    computation_trace,
    context,
    demo,
    dispatch,
    evaluations,
    expression,
    incremental,
    preparation,
    reviews,
    rule_dependencies,
    scope_epochs,
)
from app.compliance.clock import aware, use_test_clock  # noqa: E402
from app.compliance.models import (  # noqa: E402
    Authorization,
    Evaluation,
    Packet,
    ReleaseReview,
    Requirement,
)
from app.compliance.models_computation import (  # noqa: E402
    DependencyScopeEpoch,
    DependencyWitness,
    EvaluationExecution,
    RuleComputation,
)
from app.compliance.schemas_dispatch import (  # noqa: E402
    Acknowledge,
    AuthorizationInput,
    PacketPrepare,
    ReleaseDecision,
)
from app.compliance.schemas_facts import EvaluationInput  # noqa: E402
from app.document_desk.models import Document  # noqa: E402
from app.operations.cli import Demo  # noqa: E402
from app.operations.demo import seed_demo  # noqa: E402
from app.operations.models import Assignment  # noqa: E402
from app.trades.context_locks import registry_lock  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import now, uid  # noqa: E402
from app.trades.router import router  # noqa: E402,F401


@pytest.fixture()
def fixture(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    schema = "selective_test_" + uid().replace("-", "") if url else None
    engine = create_engine(url or f"sqlite:///{tmp_path / 'selective.db'}")
    if schema:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:

        @event.listens_for(engine, "connect")
        def foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    try:
        migrate(engine)
        sessions = sessionmaker(engine)
        with sessions() as db:
            fx = seed_demo(db, namespace="selective-tests")
        harness = Demo(sessions, fx)
        cn = harness.allocate("100")
        assignment = harness.assignment(cn, 0)
        with sessions() as db:
            prepared = demo.prepare(db, fx, cn["id"])
            db.commit()
        yield sessions, fx, cn, assignment, prepared
    finally:
        engine.dispose()
        if schema:
            with create_engine(url).begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def queue(db, fx, cn, action="PICKUP_CONFIRMED"):
    ctx = demo.actor(db, fx, "seller-operations")
    version = context.version(db, fx["trade_id"])
    ctx.if_match = f'"{version}"'
    value = evaluations.request(
        db, ctx, cn["id"], EvaluationInput(action=action, expected_context_version=version)
    )
    return ctx, value["evaluation_id"]


def evaluate(db, fx, cn):
    ctx, ident = queue(db, fx, cn)
    row = evaluations.complete(db, ctx, ident)
    db.flush()
    execution = db.scalar(
        select(EvaluationExecution).where(EvaluationExecution.evaluation_id == ident)
    )
    return row, execution


def captured(db, row):
    return calculation_replay.capture(db, row)[1]


def test_full_shadow_incremental_equivalence_and_fresh_identity(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    at = now()
    results = []
    with use_test_clock(lambda: at), sessions() as db:
        for strategy in ("FULL", "SHADOW", "INCREMENTAL"):
            monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", strategy)
            row, execution = evaluate(db, fx, cn)
            results.append((row.id, row.evaluation_hash, captured(db, row)["result"]))
            trace = computation_trace.read(db, demo.actor(db, fx, "seller-operations"), row.id)
            assert not trace["permission_reused"]
            if strategy == "SHADOW":
                assert execution.trace_json["shadow_equivalent"] is True
                assert execution.trace_json["shadow_rules_reused"] > 0
                assert trace["authoritative_strategy"] == "FULL"
            if strategy == "INCREMENTAL":
                assert trace["rules_reused"] > 0
                assert trace["rules_recomputed"] + trace["rules_reused"] == trace["rules_total"]
            for model in (ReleaseReview, Packet, Authorization):
                assert db.scalar(select(model).where(model.evaluation_id == row.id)) is None
            db.commit()
        assert len({r[0] for r in results}) == len({r[1] for r in results}) == 3
        assert results[0][2] == results[1][2] == results[2][2]


def test_incremental_reevaluation_requires_fresh_release_chain(fixture, monkeypatch):
    sessions, fx, cn, assignment, _ = fixture
    at = now()
    with use_test_clock(lambda: at), sessions() as db:
        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "FULL")
        old = db.get(Authorization, demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")["id"])
        old_chain = (
            old.evaluation_id,
            old.evaluation_hash,
            old.approval_id,
            old.packet_id,
            old.acknowledgment_id,
        )
        old_requirements = set(
            db.scalars(select(Requirement.id).where(Requirement.evaluation_id == old.evaluation_id))
        )
        old_packet = db.get(Packet, old.packet_id)
        db.commit()

        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
        row, execution = evaluate(db, fx, cn)
        assert execution.trace_json["rules_reused"] > 0
        assert execution.trace_json["permission_reused"] is False
        assert row.id != old.evaluation_id and row.evaluation_hash != old.evaluation_hash
        new_requirements = list(
            db.scalars(select(Requirement).where(Requirement.evaluation_id == row.id))
        )
        assert old_requirements.isdisjoint(r.id for r in new_requirements)
        for model in (ReleaseReview, Packet, Authorization):
            assert db.scalar(select(model).where(model.evaluation_id == row.id)) is None

        preparer = demo.actor(db, fx, "seller-operations")
        reviewer = demo.actor(db, fx, "seller-approver")
        carry_id = next(r.id for r in new_requirements if r.requirement_code == "CARRIED_DOCUMENTS")
        choices = [
            {
                "requirement_id": carry_id,
                "representation_type": item["representation_type"],
                "carry_method": item["carry_method"],
                "source_reference": {
                    key: value
                    for key, value in item["source_reference_json"].items()
                    if key in {"document_version_id", "attachment_id", "artifact_id"}
                },
            }
            for item in old_packet.manifest_json["items"]
        ]

        # The same calculation result does not make the previous approval applicable.
        with pytest.raises(TradeError) as rejected:
            dispatch.prepare_packet(
                db,
                preparer,
                cn["id"],
                PacketPrepare(
                    action=row.action,
                    evaluation_id=row.id,
                    evaluation_hash=row.evaluation_hash,
                    approval_id=old.approval_id,
                    selected_representations=choices,
                ),
            )
        assert rejected.value.code == "COMPLIANCE_NOT_READY"
        approval = reviews.release(
            db,
            reviewer,
            row.id,
            ReleaseDecision(
                decision="APPROVE_RELEASE",
                evaluation_hash=row.evaluation_hash,
                reason="Fresh independent review of the incremental evaluation",
            ),
        )

        def authorisation_input(packet_id, packet_hash, acknowledgment_id):
            version = context.version(db, fx["trade_id"])
            preparer.if_match = f'"{version}"'
            return AuthorizationInput(
                action=row.action,
                evaluation_id=row.id,
                evaluation_hash=row.evaluation_hash,
                approval_id=approval["id"],
                packet_id=packet_id,
                packet_hash=packet_hash,
                acknowledgment_id=acknowledgment_id,
                expected_context_version=version,
            )

        with pytest.raises(TradeError) as rejected:
            dispatch.issue(
                db,
                preparer,
                cn["id"],
                authorisation_input(old.packet_id, old.packet_hash, old.acknowledgment_id),
            )
        assert rejected.value.code == "PACKET_STALE"
        packet = dispatch.prepare_packet(
            db,
            preparer,
            cn["id"],
            PacketPrepare(
                action=row.action,
                evaluation_id=row.id,
                evaluation_hash=row.evaluation_hash,
                approval_id=approval["id"],
                selected_representations=choices,
            ),
        )
        with pytest.raises(TradeError) as rejected:
            dispatch.issue(
                db,
                preparer,
                cn["id"],
                authorisation_input(packet["id"], packet["packet_hash"], old.acknowledgment_id),
            )
        assert rejected.value.code == "PACKET_NOT_ACKNOWLEDGED"
        assert db.scalar(select(Authorization).where(Authorization.evaluation_id == row.id)) is None

        driver_role = next(
            role
            for role in ("driver-one", "driver-two")
            if fx["users"][role] == db.get(Assignment, assignment["id"]).driver_user_id
        )
        acknowledgment = dispatch.acknowledge(
            db,
            demo.actor(db, fx, driver_role),
            packet["id"],
            Acknowledge(
                packet_hash=packet["packet_hash"],
                assignment_id=assignment["id"],
                possession_confirmed=True,
                carry_methods=sorted({item["carry_method"] for item in packet["items"]}),
            ),
        )
        issued = dispatch.issue(
            db,
            preparer,
            cn["id"],
            authorisation_input(packet["id"], packet["packet_hash"], acknowledgment["id"]),
        )
        db.commit()
        fresh = db.get(Authorization, issued["id"])
        assert fresh.id != old.id
        assert (fresh.evaluation_id, fresh.evaluation_hash) == (row.id, row.evaluation_hash)
        assert fresh.approval_id != old.approval_id
        assert fresh.packet_id != old.packet_id
        assert fresh.acknowledgment_id != old.acknowledgment_id
        assert (
            old.evaluation_id,
            old.evaluation_hash,
            old.approval_id,
            old.packet_id,
            old.acknowledgment_id,
        ) == old_chain
        assert old.consumed_event_id is None


def test_pure_full_and_encrypted_replay(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        row, execution = evaluate(db, fx, cn)
        value = captured(db, row)
        before = deepcopy(value)

        # A connection listener catches accidental SQL in the calculator.
        def forbidden(*_):
            raise AssertionError("Pure calculator accessed database")

        event.listen(db.get_bind(), "before_cursor_execute", forbidden)
        try:
            assert (
                calculation.calculate_full(
                    value["snapshot"], value["rules"], aware(row.evaluated_at)
                )
                == value["result"]
            )
            assert value == before
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", forbidden)
        assert calculation_replay.recompute(db, row) == ("MATCH", [])
        assert "snapshot" not in execution.encrypted_capture_json
        assert "invoice" not in json.dumps(execution.encrypted_capture_json)
        monkeypatch.setattr(rule_dependencies, "engine_manifest", lambda: {"different": True})
        assert calculation_replay.recompute(db, row)[0] == "UNSUPPORTED_ENGINE"


def test_negative_query_and_unreviewed_upload(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        first, _ = evaluate(db, fx, cn)
        retained = captured(db, first)
        assert (
            retained["snapshot"]["lineage"]["queries"]["CARGO_INSURANCE"]["matching_revisions"]
            == []
        )
        db.commit()
        ctx = demo.actor(db, fx, "seller-operations")
        doc = Document(
            trade_id=fx["trade_id"],
            document_type="CARGO_INSURANCE",
            label="Unreviewed candidate",
            owner_organization_id=ctx.org_id,
            execution_mode="SIMULATION",
            created_by=ctx.user.id,
        )
        db.add(doc)
        db.flush()
        second, execution = evaluate(db, fx, cn)
        assert "DOCUMENT_ELIGIBILITY_CHANGED" in execution.trace_json["invalidation_reasons"]
        current = captured(db, second)
        # Query membership is reconsidered but is not an accepted, bound proof.
        assert current["snapshot"]["lineage"]["queries"]["CARGO_INSURANCE"]["matching_revisions"]
        assert current["result"]["kernels"] == retained["result"]["kernels"]
        assert doc.id not in json.dumps(current["snapshot"]["context"]["transport"])


@pytest.mark.parametrize("field", ["canonical_document_id", "current_mapping_revision_id"])
def test_document_head_changes_invalidate_dependent_basis(fixture, monkeypatch, field):
    sessions, fx, cn, _, prepared = fixture
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        first, _ = evaluate(db, fx, cn)
        before = captured(db, first)["snapshot"]
        doc = db.get(Document, prepared["invoice_document_id"])
        # Use a second existing document as canonical target; mapping is tested via witnesses
        # because mapping-head FK changes must only point at real retained mappings.
        after = deepcopy(before)
        match = after["lineage"]["queries"][doc.document_type]["matching_revisions"][0]
        match[field.replace("current_", "")] = uid()
        rule = next(
            r
            for r in captured(db, first)["rules"]
            if "invoice" in rule_dependencies.compile_rule(r)["providers"]
        )
        spec = rule_dependencies.compile_rule(rule)
        assert (
            rule_dependencies.resolve(rule, spec, before, aware(first.evaluated_at))[
                "dependency_digest"
            ]
            != rule_dependencies.resolve(rule, spec, after, aware(first.evaluated_at))[
                "dependency_digest"
            ]
        )


def test_missing_epoch_and_integrity_failure_fall_back(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        evaluate(db, fx, cn)
        db.commit()
        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
        db.execute(
            delete(DependencyScopeEpoch).where(DependencyScopeEpoch.scope_key == "global:VEHICLES")
        )
        _, execution = evaluate(db, fx, cn)
        assert "MISSING_SCOPE_RECORD" in execution.trace_json["invalidation_reasons"]
        db.commit()
        monkeypatch.setattr(
            incremental, "validate_reuse", lambda *_: "COMPUTATION_INTEGRITY_FAILED"
        )
        _, execution = evaluate(db, fx, cn)
        assert execution.trace_json["rules_reused"] == 0
        assert "COMPUTATION_INTEGRITY_FAILED" in execution.trace_json["invalidation_reasons"]


def test_expiry_without_event_and_queued_stale_rejection(fixture, monkeypatch):
    sessions, fx, cn, assignment, _ = fixture
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        first, _ = evaluate(db, fx, cn)
        until = aware(first.valid_until)
        db.commit()
    with use_test_clock(lambda: until), sessions() as db:
        _, execution = evaluate(db, fx, cn)
        assert execution.trace_json["rules_reused"] == 0
        assert "VALIDITY_BOUNDARY_REACHED" in execution.trace_json["invalidation_reasons"]
        db.commit()
        ctx, ident = queue(db, fx, cn)
        row = db.get(Assignment, assignment["id"])
        row.status = "CANCELLED"
        db.flush()
        stale = evaluations.complete(db, ctx, ident)
        assert stale.job_state == "COMPLETED_STALE"
        assert stale.decision == "BLOCKED"


def test_assignment_change_rejects_old_permission_in_incremental_mode(fixture, monkeypatch):
    sessions, fx, cn, assignment, _ = fixture
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.get(Assignment, assignment["id"]).status = "CANCELLED"
        db.flush()
        assert (
            dispatch.read(db, demo.actor(db, fx, "seller-operations"), token["id"])[
                "effective_state"
            ]
            != "ACTIVE"
        )
        _, execution = evaluate(db, fx, cn)
        assert "ASSIGNMENT_CHANGED" in execution.trace_json["invalidation_reasons"]


def test_epoch_scope_move_and_rollback(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        evaluate(db, fx, cn)
        db.commit()
        old = scope_epochs.key(fx["trade_id"], "DOC:TAX_INVOICE")
        new = scope_epochs.key(fx["trade_id"], "DOC:DELIVERY_CHALLAN")
        before = {
            r.scope_key: r.epoch
            for r in db.scalars(
                select(DependencyScopeEpoch).where(DependencyScopeEpoch.scope_key.in_([old, new]))
            )
        }
        doc = db.scalar(
            select(Document).where(
                Document.trade_id == fx["trade_id"], Document.document_type == "TAX_INVOICE"
            )
        )
        doc.document_type = "DELIVERY_CHALLAN"
        db.flush()
        db.expire_all()
        for key in (old, new):
            assert db.get(DependencyScopeEpoch, key).epoch > before[key]
        db.rollback()
        for key in (old, new):
            assert db.get(DependencyScopeEpoch, key).epoch == before[key]


def test_history_is_immutable_and_trace_is_authorized(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        row, _ = evaluate(db, fx, cn)
        db.commit()
        for model, field in (
            (RuleComputation, "content_hash"),
            (DependencyWitness, "content_hash"),
        ):
            with pytest.raises(DBAPIError):
                with db.begin_nested():
                    db.execute(update(model).values(**{field: "altered"}))
        trace = computation_trace.read(db, demo.actor(db, fx, "seller-operations"), row.id)
        wire = json.dumps(trace)
        assert "matching_revisions" not in wire and "ciphertext" not in wire and "PAN" not in wire
        with pytest.raises(TradeError):
            computation_trace.read(db, demo.actor(db, fx, "unrelated"), row.id)


def test_dependency_closure_no_short_circuit_and_unknown_provider():
    expr = {
        "op": "and",
        "args": [
            {"op": "literal", "value": False},
            {
                "op": "eq",
                "args": [
                    {"op": "field", "path": "proof.unregistered"},
                    {"op": "literal", "value": True},
                ],
            },
        ],
    }
    assert expression.dependencies(expr) == ["proof.unregistered"]
    rule = {
        "id": uid(),
        "hash": "test",
        "requirement_code": "TEST",
        "definition": {
            "applicability_expression": expr,
            "satisfaction_expression": expr,
            "date_basis": "ACTION_TIME",
            "effective_from": now().isoformat(),
        },
    }
    assert not rule_dependencies.compile_rule(rule)["reusable"]


def test_unrelated_invoice_change_does_not_invalidate_transport_kernel(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        row, _ = evaluate(db, fx, cn)
        value = captured(db, row)
        snapshot = value["snapshot"]
        rule = next(r for r in value["rules"] if r["requirement_code"] == "TRANSPORT_ASSURANCE")
        spec = rule_dependencies.compile_rule(rule)
        at = aware(row.evaluated_at)
        before = rule_dependencies.resolve(rule, spec, snapshot, at)
        after = deepcopy(snapshot)
        after["data"]["invoice"]["description"] = "Corrected product description"
        after["context"]["documents"][0]["fact_hash"] = "new-reviewed-description"
        after["lineage"]["queries"]["TAX_INVOICE"]["matching_revisions"][0][
            "reviewed_fact_revision_id"
        ] = uid()
        assert (
            rule_dependencies.resolve(rule, spec, after, at)["dependency_digest"]
            == before["dependency_digest"]
        )


@pytest.mark.parametrize("change", ["proof", "assignment", "hold", "corridor", "registry"])
def test_changed_snapshot_matches_full_reference(fixture, monkeypatch, change):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        row, _ = evaluate(db, fx, cn)
        value = captured(db, row)
        snapshot, rules, at = value["snapshot"], value["rules"], aware(row.evaluated_at)
        if change == "proof":
            snapshot["data"]["proof"]["transport_assurance"] = False
        elif change == "assignment":
            snapshot["context"]["assignment"]["driver_user_id"] = uid()
        elif change == "hold":
            snapshot["context"]["holds"] = [{"active": True}]
        elif change == "corridor":
            snapshot["context"]["corridor_intelligence"] = {"outcome": "BLOCKED"}
        else:
            snapshot["registry"]["epoch"] += 1
        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
        result, bundle = incremental.execute(
            db, demo.actor(db, fx, "seller-operations"), row, snapshot, rules, at
        )
        assert result == calculation.calculate_full(snapshot, rules, at)
        if change in {"hold", "corridor"}:
            assert result["decision"] == "BLOCKED"
            assert bundle["trace"]["rules_reused"] > 0


def test_shadow_mismatch_remains_full_and_redis_is_not_freshness_authority(fixture, monkeypatch):
    import redis

    sessions, fx, cn, *_ = fixture

    def offline(*args, **kwargs):
        raise redis.ConnectionError("Redis unavailable")

    monkeypatch.setattr(redis.Redis, "from_url", offline)
    with sessions() as db:
        row, _ = evaluate(db, fx, cn)
        value = captured(db, row)
        original = incremental.validate_reuse

        # Corrupt only the in-memory candidate after successful integrity validation.
        def wrong_candidate(db, prior, *args):
            problem = original(db, prior, *args)
            if not problem:
                altered = deepcopy(prior.result_json)
                altered["outcome"] = "UNKNOWN"
                prior.__dict__["result_json"] = altered
            return problem

        monkeypatch.setattr(incremental, "validate_reuse", wrong_candidate)
        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "SHADOW")
        result, bundle = incremental.execute(
            db,
            demo.actor(db, fx, "seller-operations"),
            row,
            value["snapshot"],
            value["rules"],
            aware(row.evaluated_at),
        )
        assert result == value["result"]
        assert bundle["trace"]["shadow_equivalent"] is False
        assert bundle["trace"]["authoritative_strategy"] == "FULL"


def test_not_applicable_keeps_dependencies_and_future_boundary(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        row, _ = evaluate(db, fx, cn)
        value = captured(db, row)
        rule = deepcopy(value["rules"][0])
        at = aware(row.evaluated_at)
        rule["definition"]["date_basis"] = "ACTION_TIME"
        rule["definition"]["effective_from"] = (at + timedelta(seconds=10)).isoformat()
        rule["definition"]["applicability_expression"] = {"op": "literal", "value": True}
        result = calculation.calculate_full(value["snapshot"], [rule], at)
        assert result["requirements"][0]["outcome"] == "NOT_APPLICABLE"
        assert calculation.timestamp(result["valid_until"]) <= at + timedelta(seconds=10)
        spec = rule_dependencies.compile_rule(rule)
        assert rule_dependencies.resolve(rule, spec, value["snapshot"], at)["witnesses"]
        next_result = calculation.calculate_full(
            value["snapshot"], [rule], at + timedelta(seconds=10)
        )
        assert next_result["requirements"][0]["applicability"] == "APPLICABLE"


def test_dispatch_captured_replay_through_existing_product_service(fixture, monkeypatch):
    from app.product import replay, schemas
    from app.trades.models import Grant, Membership

    sessions, fx, cn, *_ = fixture
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        ctx = demo.actor(db, fx, "seller-operations")
        member = db.scalar(
            select(Membership).where(
                Membership.user_id == ctx.user.id, Membership.organization_id == ctx.org_id
            )
        )
        db.add(
            Grant(
                membership_id=member.id,
                permission_code="evidence.replay.request",
                capability="EVIDENCE_ANALYST",
                created_by=ctx.user.id,
            )
        )
        db.flush()
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        authorization = db.get(Authorization, token["id"])
        evaluation = db.get(Evaluation, authorization.evaluation_id)
        queued = replay.request(
            db,
            ctx,
            None,
            schemas.ReplayInput(
                subject_type="DISPATCH_AUTHORISATION",
                subject_id=authorization.id,
                replay_kind="RECOMPUTE_CAPTURED_INPUTS",
                source_manifest_hash=evaluation.dependency_hash,
                expected_engine_version=evaluation.engine_version,
            ),
        )
        result = replay.complete(db, ctx, queued["id"])
        assert result.result_json["input_integrity"] == "PASS"
        assert result.result_json["recomputation"] == "MATCH"
        assert result.result_json["current_readiness"] == "NOT_ASSESSED_BY_REPLAY"
        assert replay.read(db, ctx, queued["id"])["differences"] == []
        assert authorization.consumed_event_id is None


def test_postgresql_epoch_mutation_serializes_with_evaluation(fixture, monkeypatch):
    sessions, fx, cn, assignment, _ = fixture
    if sessions.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Requires disposable PostgreSQL")
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        evaluate(db, fx, cn)
        db.commit()
    barrier = Barrier(2)

    def task(change):
        barrier.wait(timeout=10)
        with sessions() as db:
            ctx = demo.actor(db, fx, "seller-operations")
            context.access(db, ctx, cn["id"], "compliance.read", False, True)
            if change:
                db.get(Assignment, assignment["id"]).status = "CANCELLED"
                db.flush()
            else:
                row, execution = evaluate(db, fx, cn)
                assert row.decision in {"BLOCKED", "ELIGIBLE_FOR_REVIEW"}
                assert execution.trace_json["permission_reused"] is False
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(task, [False, True]))
    with sessions() as db:
        row, execution = evaluate(db, fx, cn)
        # Preserve reference semantics: cancellation blocks issuance/consumption in dispatch,
        # even where individual document predicates still pass.
        value = captured(db, row)
        assert value["result"] == calculation.calculate_full(
            value["snapshot"], value["rules"], aware(row.evaluated_at)
        )
        assert db.get(Assignment, assignment["id"]).status == "CANCELLED"
        assert db.scalar(select(Authorization).where(Authorization.evaluation_id == row.id)) is None
        assert (
            "ASSIGNMENT_CHANGED" in execution.trace_json["invalidation_reasons"]
            or execution.trace_json["rules_recomputed"] == 0
        )


def test_benchmark_preparation_and_execution_separately(fixture, monkeypatch):
    """Synthetic fixture measurements, not a production performance claim."""
    sessions, fx, cn, *_ = fixture
    engine = sessions.kw["bind"]
    samples = []
    sql = [0]

    def count(*_):
        sql[0] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        with sessions() as db:
            evaluate(db, fx, cn)
            db.commit()
            for strategy in ("FULL", "SHADOW", "INCREMENTAL"):
                for _ in range(3):
                    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", strategy)
                    start = perf_counter_ns()
                    registry_lock(db)
                    acquired = perf_counter_ns()
                    ctx, ident = queue(db, fx, cn)
                    row, trade, subject, _ = evaluations.exact(db, ctx, ident)
                    sql[0] = 0
                    prep, prep_cpu = perf_counter_ns(), process_time_ns()
                    snapshot, rules = preparation.prepare_snapshot(db, trade, subject, row, now())
                    prepared_ns, prep_cpu_ns = (
                        perf_counter_ns() - prep,
                        process_time_ns() - prep_cpu,
                    )
                    prep_queries = sql[0]
                    sql[0] = 0
                    result, bundle = incremental.execute(
                        db,
                        ctx,
                        row,
                        snapshot,
                        rules,
                        calculation.timestamp(snapshot["assessment_time"]),
                    )
                    execution_queries = sql[0]
                    sql[0] = 0
                    persist = perf_counter_ns()
                    evaluations.persist_evaluation(
                        db,
                        ctx,
                        row,
                        result,
                        calculation.timestamp(snapshot["assessment_time"]),
                        bundle,
                    )
                    db.flush()
                    persist_ns = perf_counter_ns() - persist
                    persistence_queries = sql[0]
                    db.commit()
                    released = perf_counter_ns()
                    retained_execution = db.scalar(
                        select(EvaluationExecution).where(
                            EvaluationExecution.evaluation_id == row.id
                        )
                    )
                    new_computations = list(
                        db.scalars(
                            select(RuleComputation).where(
                                RuleComputation.origin_evaluation_id == row.id
                            )
                        )
                    )
                    witnesses = list(
                        db.scalars(
                            select(DependencyWitness).where(
                                DependencyWitness.computation_id.in_(
                                    [c.id for c in new_computations]
                                )
                            )
                        )
                    )
                    storage_bytes = (
                        len(json.dumps(retained_execution.encrypted_capture_json).encode())
                        + sum(
                            len(json.dumps(c.result_json).encode())
                            + len(json.dumps(c.supporting_references_json).encode())
                            for c in new_computations
                        )
                        + sum(len(json.dumps(w.witness_json).encode()) for w in witnesses)
                    )
                    db.commit()
                    samples.append(
                        {
                            "strategy": strategy,
                            "preparation_wall_ns": prepared_ns,
                            "preparation_cpu_ns": prep_cpu_ns,
                            "preparation_sql": prep_queries,
                            "execution_sql": execution_queries,
                            "persistence_sql": persistence_queries,
                            "persistence_wall_ns": persist_ns,
                            "lock_wait_ns": acquired - start,
                            "transaction_lock_window_ns": released - acquired,
                            "new_history_json_bytes": storage_bytes,
                            "new_computations": len(new_computations),
                            "new_witnesses": len(witnesses),
                            "trace": bundle["trace"],
                            "capture_plaintext_bytes": len(json.dumps(bundle["snapshot"])),
                        }
                    )
        target = Path(f"artifacts/audit/selective-compliance-benchmark-{engine.dialect.name}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "fixture": f"Synthetic domestic demo, {engine.dialect.name}; "
                    "3 warm iterations per mode",
                    "engine_manifest": rule_dependencies.engine_manifest(),
                    "samples": samples,
                },
                indent=2,
            )
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)
