"""Boundary, privacy, stale-evidence and immutable-history release acceptance."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import (  # noqa: E402
    bindings,
    context,
    demo,
    dispatch,
    evaluations,
    facts,
    governance,
    handoff,
    reviews,
    templates,
    turnover,
)
from app.compliance.models import Authorization, Binding, Evaluation, Pack, Turnover  # noqa: E402
from app.compliance.schemas_dispatch import Reason, ReleaseDecision  # noqa: E402
from app.compliance.schemas_facts import (  # noqa: E402
    BindingPrepare,
    DeclarationReview,
    EvaluationInput,
    EvidenceBindings,
    FactPrepare,
    Facts,
)
from app.operations.cli import Demo  # noqa: E402
from app.operations.demo import seed_demo  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import now, uid  # noqa: E402
from app.trades.router import router  # noqa: E402,F401


@pytest.fixture()
def fixture(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    schema = "trade_phase4_test_" + uid().replace("-", "") if url else None
    engine = create_engine(url or f"sqlite:///{tmp_path / 'gate.db'}")
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        migrate(engine)
        sessions = sessionmaker(engine)
        with sessions() as db:
            fx = seed_demo(db, namespace="phase4-policy-test")
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
            cleanup = create_engine(url)
            with cleanup.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            cleanup.dispose()


def evaluate_current(db, fx, cn, action="PICKUP_CONFIRMED"):
    actor = demo.actor(db, fx, "seller-operations")
    actor.if_match = f'"{context.version(db, fx["trade_id"])}"'
    requested = evaluations.request(
        db,
        actor,
        cn["id"],
        EvaluationInput(
            action=action, expected_context_version=context.version(db, fx["trade_id"])
        ),
    )
    row = evaluations.complete(db, actor, requested["evaluation_id"])
    return evaluations.read(db, actor, row.id)


def rebind(db, fx, cn, changes):
    head = context.heads(db, db.get(demo.Consignment, cn["id"]))
    bound = db.get(Binding, head.current_binding_revision_id)
    data = {
        k: deepcopy(v) for k, v in bound.binding_json.items() if k in EvidenceBindings.model_fields
    }
    data.update(changes)
    actor = demo.actor(db, fx, "seller-operations")
    actor.if_match = f'"{context.version(db, fx["trade_id"])}"'
    return bindings.prepare(
        db,
        actor,
        cn["id"],
        BindingPrepare(expected_context_version=context.version(db, fx["trade_id"]), bindings=data),
    )


@pytest.mark.parametrize(
    "value,expected", [("4999999", False), ("5000000", False), ("5000001", True), (None, None)]
)
def test_issued_value_strict_ewb_boundary(value, expected):
    from app.compliance.expression import evaluate

    rule = next(
        r for r in templates.candidate([uid()]).rules if r.requirement_code == "EWB_REQUIRED"
    )
    assert (
        evaluate(
            rule.applicability_expression,
            {"invoice": {"grand_total_minor": value}, "quote": {"grand_total_minor": "1"}},
        )
        is expected
    )


@pytest.mark.parametrize("amount,expected", [("5000000000", None), ("5000000001", True)])
def test_known_positive_turnover_does_not_require_complete_history(amount, expected):
    assert (
        turnover.derive(
            {
                "assessment_invoice_date": "2026-04-01",
                "relevant_financial_years": [
                    {
                        "financial_year_start": 2024,
                        "existence_status": "IN_EXISTENCE",
                        "pan_aggregate_turnover_minor": amount,
                    }
                ],
                "history_completeness_declared": False,
                "supplier_exclusion_code": "NONE_CLAIMED",
            }
        )["exceeds_five_crore"]
        is expected
    )


def test_current_fiscal_year_and_unknown_exclusion_cannot_prove_applicability():
    value = turnover.derive(
        {
            "assessment_invoice_date": "2026-04-01",
            "relevant_financial_years": [
                {
                    "financial_year_start": 2026,
                    "existence_status": "IN_EXISTENCE",
                    "pan_aggregate_turnover_minor": "90000000000",
                }
            ],
            "history_completeness_declared": False,
            "supplier_exclusion_code": "UNKNOWN",
        }
    )
    assert value["exceeds_five_crore"] is None
    assert value["exclusion_resolved"] is None


def test_durable_worker_evaluates_without_a_document_version(fixture):
    from app.document_desk.worker import run_one

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        actor = demo.actor(db, fx, "seller-operations")
        actor.if_match = f'"{context.version(db, fx["trade_id"])}"'
        queued = evaluations.request(
            db,
            actor,
            cn["id"],
            EvaluationInput(
                action="PICKUP_CONFIRMED",
                expected_context_version=context.version(db, fx["trade_id"]),
            ),
        )
        row = db.get(Evaluation, queued["evaluation_id"])
        job_id = row.job_id
        db.commit()
    assert run_one(sessions, job_id)
    with sessions() as db:
        row = db.get(Evaluation, queued["evaluation_id"])
        assert row.job_state == "COMPLETED"
        assert row.decision == "ELIGIBLE_FOR_REVIEW"


@pytest.mark.parametrize(
    "change",
    [
        {"over_dimensional_cargo_declared": True},
        {"special_valuation_profile": "IDENTIFIED_SPECIAL_PROFILE"},
        {"reverse_charge_position": "YES"},
        {"supply_taxability": "EXEMPT"},
        {"document_issue_scenario": "ONE_INVOICE_MULTIPLE_DISPATCHES"},
        {"declared_transit_state_codes": ["32"]},
        {"scope_profile_code": "UNKNOWN_PROFILE"},
    ],
)
def test_unsupported_facts_cannot_be_approved(fixture, change):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        current = context.public_context(db, demo.actor(db, fx, "seller-operations"), cn["id"])
        data = {k: v for k, v in current["effective_facts"].items() if k in Facts.model_fields}
        data["field_provenance"] = {}
        data.update(change)
        actor = demo.actor(db, fx, "seller-operations")
        actor.if_match = current["etag"]
        prepared = facts.prepare(
            db,
            actor,
            cn["id"],
            FactPrepare(
                expected_context_version=current["context_version"],
                facts=data,
                submit_for_review=True,
            ),
        )
        facts.review(
            db,
            demo.actor(db, fx, "seller-approver"),
            prepared["id"],
            DeclarationReview(
                decision="APPROVE_DECLARATION", reason="Independent test declaration"
            ),
        )
        rebind(db, fx, cn, {"compliance_fact_revision_id": prepared["id"]})
        outcome = evaluate_current(db, fx, cn)
        assert outcome["decision"] == "UNSUPPORTED"
        with pytest.raises(TradeError) as error:
            reviews.release(
                db,
                demo.actor(db, fx, "seller-approver"),
                outcome["id"],
                ReleaseDecision(
                    decision="APPROVE_RELEASE",
                    evaluation_hash=outcome["evaluation_hash"],
                    reason="No waiver",
                ),
            )
        assert error.value.code == "COMPLIANCE_NOT_READY"


def test_missing_ewb_is_an_explained_blocker(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        bound = db.get(
            Binding,
            context.heads(db, db.get(demo.Consignment, cn["id"])).current_binding_revision_id,
        )
        invoice_version = bound.binding_json["movement_document"]["document_version_id"]
        from app.document_desk.models import VerificationCheck, VerificationResult

        results = [
            i
            for i in bound.binding_json["verification_result_ids"]
            if db.get(
                VerificationCheck, db.get(VerificationResult, i).verification_check_id
            ).document_version_id
            == invoice_version
        ]
        rebind(db, fx, cn, {"supporting_documents": [], "verification_result_ids": results})
        outcome = evaluate_current(db, fx, cn)
        assert outcome["decision"] == "BLOCKED"
        ewb = next(r for r in outcome["requirements"] if r["requirement_code"] == "EWB_REQUIRED")
        assert ewb["outcome"] == "FAILED" and ewb["explanation"] and ewb["remedies_json"]


@pytest.mark.parametrize("role", ["seller-operations", "carrier-dispatcher"])
def test_preparer_or_generic_admin_cannot_approve_release(fixture, role):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        outcome = evaluate_current(db, fx, cn)
        with pytest.raises(TradeError) as error:
            reviews.release(
                db,
                demo.actor(db, fx, role),
                outcome["id"],
                ReleaseDecision(
                    decision="APPROVE_RELEASE",
                    evaluation_hash=outcome["evaluation_hash"],
                    reason="Test segregation",
                ),
            )
        assert error.value.code in {"SELF_REVIEW_NOT_ALLOWED", "FORBIDDEN"}


@pytest.mark.parametrize("role", ["buyer-receiver", "carrier-dispatcher", "driver-one"])
def test_private_pan_not_accessible_or_exported(fixture, role):
    sessions, fx, cn, _, prepared = fixture
    with sessions() as db:
        bound = db.get(Binding, prepared["binding_id"])
        with pytest.raises(TradeError):
            turnover.read(db, demo.actor(db, fx, role), bound.turnover_declaration_id)
        outcome = evaluate_current(db, fx, cn)
        exported = handoff.evidence(db, demo.actor(db, fx, role), outcome["id"])
        import json

        raw = json.dumps(exported)
        private = db.get(Turnover, bound.turnover_declaration_id)
        assert private.id not in raw and private.pan_identity_reference not in raw
        assert "pan_aggregate_turnover_minor" not in raw
        assert "declared_business_commencement_date" not in raw


def test_returning_effective_facts_invalidates_unused_token(fixture):
    sessions, fx, cn, _, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        bound = db.get(Binding, prepared["binding_id"])
        facts.review(
            db,
            demo.actor(db, fx, "seller-approver"),
            bound.fact_revision_id,
            DeclarationReview(
                decision="RETURN_FOR_CORRECTION", reason="Material declaration correction"
            ),
        )
        assert (
            dispatch.read(db, demo.actor(db, fx, "driver-one"), token["id"])["effective_state"]
            == "EVALUATION_STALE"
        )
        assert db.get(Authorization, token["id"]).consumed_event_id is None


@pytest.mark.parametrize("changed", ["hash", "scan", "archive"])
def test_source_security_changes_make_packet_stale(fixture, changed):
    from app.document_desk.models import Document
    from app.operations.models import Attachment

    sessions, fx, cn, _, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        if changed == "archive":
            db.get(Document, prepared["invoice_document_id"]).lifecycle_status = "ARCHIVED"
        elif changed == "hash":
            db.get(Attachment, prepared["invoice_attachment_id"]).sha256 = "0" * 64
        else:
            db.get(Attachment, prepared["invoice_attachment_id"]).security_state = "QUARANTINED"
        assert (
            dispatch.read(db, demo.actor(db, fx, "driver-one"), token["id"])["effective_state"]
            == "EVALUATION_STALE"
        )


def test_stale_queued_job_never_promotes_old_context(fixture):
    from app.trades.context_locks import bump_context

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        actor = demo.actor(db, fx, "seller-operations")
        actor.if_match = f'"{context.version(db, fx["trade_id"])}"'
        queued = evaluations.request(
            db,
            actor,
            cn["id"],
            EvaluationInput(
                action="PICKUP_CONFIRMED",
                expected_context_version=context.version(db, fx["trade_id"]),
            ),
        )
        bump_context(db, fx["trade_id"], "DOCUMENT_SOURCE_REPLACED")
        row = evaluations.complete(db, actor, queued["evaluation_id"])
        assert row.job_state == "COMPLETED_STALE" and row.decision == "BLOCKED"


def test_suspended_pack_invalidates_tokens_without_rewriting_history(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        pack = db.scalar(select(Pack).where(Pack.environment == "SIMULATION"))
        before = db.get(Evaluation, token["evaluation_id"]).evaluation_hash
        governance.suspend(
            db,
            demo.actor(db, fx, "seller-approver"),
            pack.id,
            Reason(reason="Adverse source review"),
        )
        assert (
            dispatch.read(db, demo.actor(db, fx, "driver-one"), token["id"])["effective_state"]
            == "EVALUATION_STALE"
        )
        assert db.get(Evaluation, token["evaluation_id"]).evaluation_hash == before


@pytest.mark.parametrize("target", ["evaluation", "authorisation"])
def test_database_preserves_completed_history(fixture, target):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
    with sessions() as db:
        row = db.get(
            Evaluation if target == "evaluation" else Authorization,
            token["evaluation_id"] if target == "evaluation" else token["id"],
        )
        if target == "evaluation":
            row.decision = "BLOCKED"
        else:
            row.expires_at = now() + timedelta(days=100)
        with pytest.raises(DBAPIError):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("same_command", [False, True])
def test_postgresql_parallel_consumption_is_atomic(fixture, same_command):
    from app.operations import movement
    from app.operations.models import Event
    from app.operations.schemas import ShipmentEventInput

    sessions, fx, cn, assignment, prepared = fixture
    if sessions.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Row/advisory-lock concurrency requires disposable PostgreSQL")
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
    body = {
        "client_event_id": uid(),
        "event_type": "PICKUP_CONFIRMED",
        "assignment_id": assignment["id"],
        "dispatch_authorization_id": token["id"],
        "loading_manifest_revision_id": prepared["manifest_id"],
        "occurred_at": now(),
        "payload": {
            "actual_gross_weight_kg": "400",
            "actual_package_count": 4,
            "items": [
                {
                    "consignment_item_id": i["id"],
                    "loaded_quantity": i["allocated_quantity"],
                    "uqc": i["uqc"],
                }
                for i in cn["items"]
            ],
        },
    }
    start = Barrier(2)

    def consume(index):
        data = {**body, "client_event_id": body["client_event_id"] if same_command else uid()}
        start.wait(timeout=10)
        with sessions() as db:
            try:
                result = movement.event(
                    db,
                    demo.actor(db, fx, "driver-one"),
                    cn["id"],
                    ShipmentEventInput.model_validate(data),
                )
                db.commit()
                return "SUCCESS", result["id"]
            except TradeError as error:
                db.rollback()
                return error.code, None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(consume, [0, 1]))
    assert sum(code == "SUCCESS" for code, _ in results) == (2 if same_command else 1)
    with sessions() as db:
        events = list(
            db.scalars(
                select(Event).where(
                    Event.consignment_id == cn["id"], Event.event_type == "PICKUP_CONFIRMED"
                )
            )
        )
        assert len(events) == 1
        assert db.get(Authorization, token["id"]).consumed_event_id == events[0].id


def test_future_rule_boundary_stales_token_without_a_mutation(fixture):
    from app.compliance.clock import aware, use_test_clock
    from app.compliance.schemas_rules import PackReview, PackTestInput, PublishInput

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        active = db.scalar(select(Pack).where(Pack.environment == "SIMULATION"))
        at = now()
        draft = templates.candidate(active.source_ids, version="scheduled")
        draft.effective_from = at + timedelta(seconds=60)
        future = governance.create_pack(db, demo.actor(db, fx, "seller-operations"), None, draft)
        tested = governance.test_pack(
            db,
            demo.actor(db, fx, "seller-operations"),
            future["id"],
            PackTestInput(
                pack_hash=future["content_hash"], test_suite_id="PH4_REQUIRED_BOUNDARIES_V1"
            ),
        )
        approved = governance.review_pack(
            db,
            demo.actor(db, fx, "seller-approver"),
            future["id"],
            PackReview(
                pack_hash=future["content_hash"],
                passed_test_run_id=tested["id"],
                reason="Future exact version",
            ),
        )
        governance.publish(
            db,
            demo.actor(db, fx, "seller-approver"),
            future["id"],
            PublishInput(pack_hash=future["content_hash"], review_approval_event_id=approved["id"]),
        )
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        assert aware(db.get(Authorization, token["id"]).expires_at) <= draft.effective_from
        db.commit()
    with use_test_clock(lambda: draft.effective_from):
        with sessions() as db:
            assert (
                dispatch.read(db, demo.actor(db, fx, "driver-one"), token["id"])["effective_state"]
                != "ACTIVE"
            )


def pickup_command(cn, assignment, prepared, token):
    from app.operations.schemas import ShipmentEventInput

    return ShipmentEventInput(
        client_event_id=uid(),
        assignment_id=assignment["id"],
        event_type="PICKUP_CONFIRMED",
        dispatch_authorization_id=token["id"],
        loading_manifest_revision_id=prepared["manifest_id"],
        occurred_at=now(),
        payload={
            "actual_gross_weight_kg": "400",
            "actual_package_count": 4,
            "items": [
                {
                    "consignment_item_id": i["id"],
                    "loaded_quantity": i["allocated_quantity"],
                    "uqc": i["uqc"],
                }
                for i in cn["items"]
            ],
        },
    )


@pytest.mark.parametrize("changed", ["active", "registration", "capacity"])
def test_current_vehicle_invalidates_authorisation(fixture, changed):
    from app.operations.models import Vehicle

    sessions, fx, cn, assignment, _ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        vehicle = db.get(Vehicle, assignment["vehicle_id"])
        if changed == "active":
            vehicle.active = False
        else:
            data = dict(vehicle.vehicle_json)
            key = (
                "registration_number"
                if changed == "registration"
                else "declared_payload_capacity_kg"
            )
            data[key] = "KA99TEST0001" if changed == "registration" else "100"
            vehicle.vehicle_json = data
        db.commit()
        assert (
            dispatch.read(db, demo.actor(db, fx, "driver-one"), token["id"])["effective_state"]
            != "ACTIVE"
        )
        assert evaluate_current(db, fx, cn)["decision"] == "BLOCKED"


def test_projection_retry_cannot_duplicate_movement(fixture):
    from app.compliance import projection
    from app.compliance.models import MovementProjection
    from app.document_desk.models import Job
    from app.operations import movement
    from app.operations.models import Event

    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        command = pickup_command(cn, assignment, prepared, token)
        actor = demo.actor(db, fx, "driver-one")
        movement.event(db, actor, cn["id"], command)
        db.commit()
        job = db.scalar(select(Job).where(Job.stage == projection.STAGE))
        first = projection.deliver(db, actor, job)
        db.flush()
        assert projection.deliver(db, actor, job).id == first.id
        db.commit()
        assert len(db.scalars(select(MovementProjection)).all()) == 1
        assert (
            len(db.scalars(select(Event).where(Event.event_type == "PICKUP_CONFIRMED")).all()) == 1
        )


def test_expired_token_cannot_use_backdated_actual_movement(fixture):
    from app.compliance.clock import aware, use_test_clock
    from app.operations import movement

    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        command = pickup_command(cn, assignment, prepared, token)
        expiry = aware(db.get(Authorization, token["id"]).expires_at)
        db.commit()
    with use_test_clock(lambda: expiry):
        with sessions() as db:
            with pytest.raises(TradeError) as error:
                movement.event(db, demo.actor(db, fx, "driver-one"), cn["id"], command)
            assert error.value.code == "AUTHORISATION_EXPIRED"
            db.rollback()
            assert db.get(Authorization, token["id"]).consumed_event_id is None


@pytest.mark.parametrize("role", ["carrier-dispatcher", "driver-two", "buyer-receiver"])
def test_other_actors_cannot_access_assigned_packet_copy(fixture, role):
    from app.compliance import packet_files
    from app.compliance.models import PacketItem

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        item = db.scalar(select(PacketItem).where(PacketItem.packet_id == token["packet_id"]))
        with pytest.raises(TradeError):
            packet_files.descriptor(db, demo.actor(db, fx, role), token["packet_id"], item.id)


def test_constraints_separate_authority_expiry_and_policy_freshness(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        evaluated = evaluate_current(db, fx, cn)
        contract = handoff.constraints(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert contract["evaluation_hash"] == evaluated["evaluation_hash"]
        assert contract["dependency_hash"]
        assert any(
            d["code"] == "EWB_AUTHORITY_EXPIRY" and d["class"] == "LEGAL"
            for d in contract["deadlines"]
        )
        assert any(
            d["code"] == "OBSERVATION_FRESHNESS" and d["class"] == "APPLICATION_POLICY"
            for d in contract["deadlines"]
        )
        ledger = handoff.evidence(db, demo.actor(db, fx, "seller-operations"), evaluated["id"])
        types = {n["type"] for n in ledger["graph"]["nodes"]}
        assert {"Declaration", "LoadingManifest", "Verification", "DocumentFacts"} <= types
        assert all(r["evidence_refs_json"] for r in ledger["requirements"])


def test_revoked_driver_membership_prevents_consumption(fixture):
    from app.operations import movement
    from app.trades.models import Membership

    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == fx["users"]["driver-one"],
                Membership.organization_id == fx["organizations"]["carrier"],
            )
        )
        membership.status = "SUSPENDED"
        db.commit()
        with pytest.raises(TradeError):
            movement.event(
                db,
                demo.actor(db, fx, "driver-one"),
                cn["id"],
                pickup_command(cn, assignment, prepared, token),
            )
        db.rollback()
        assert db.get(Authorization, token["id"]).consumed_event_id is None


@pytest.mark.parametrize("status", ["HELD", "WITHDRAWN", "UNKNOWN"])
def test_nonactive_source_cannot_be_reviewed_for_publication(fixture, status):
    from app.compliance.models import Source
    from app.compliance.schemas_rules import SourceInput

    sessions, fx, _, *_ = fixture
    with sessions() as db:
        original = db.scalar(select(Source))
        definition = {**original.source_json, "source_status": status}
        registered = governance.source(
            db,
            demo.actor(db, fx, "seller-operations"),
            None,
            SourceInput.model_validate(definition),
        )
        candidate = governance.create_pack(
            db,
            demo.actor(db, fx, "seller-operations"),
            None,
            templates.candidate([registered["id"]], version=status),
        )
        with pytest.raises(TradeError) as error:
            governance.sources_current(db, db.get(Pack, candidate["id"]), strict=True)
        assert error.value.code == "SOURCE_CONFLICT_UNRESOLVED"


@pytest.mark.parametrize("bad", ["vehicle", "part", "cancelled", "expired"])
def test_unselected_adverse_ewb_observation_cannot_be_hidden(fixture, bad):
    from app.document_desk.models import (
        Document,
        FactRevision,
        VerificationCheck,
        VerificationResult,
        Version,
    )

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        original = db.scalar(
            select(VerificationResult)
            .join(VerificationCheck)
            .where(VerificationCheck.check_type == "EWB_AUTHORITY_LOOKUP")
        )
        check = db.get(VerificationCheck, original.verification_check_id)
        fact = db.get(FactRevision, check.fact_revision_id)
        doc = db.get(Document, db.get(Version, fact.document_version_id).document_id)
        data = deepcopy(original.result_json["normalised_result"])
        key, value = {
            "vehicle": ("vehicle_registration_number", "WRONG"),
            "part": ("part_information", "PART_A_ONLY"),
            "cancelled": ("status", "CANCELLED"),
            "expired": ("status", "EXPIRED"),
        }[bad]
        data[key] = value
        demo.observations(
            db,
            demo.actor(db, fx, "seller-operations"),
            doc,
            fact.canonical_document_json,
            data,
            "EWB_AUTHORITY_LOOKUP",
        )
        evaluated = evaluate_current(db, fx, cn)
        assert evaluated["decision"] == "BLOCKED"
        assert any(
            r["requirement_code"] == "EWB_IDENTITY" and r["outcome"] == "FAILED"
            for r in evaluated["requirements"]
        )


@pytest.mark.parametrize("outcome", ["UNAVAILABLE", "NOT_AUTHORISED"])
def test_provider_failure_is_unknown_not_a_negative_taxpayer_finding(fixture, outcome):
    from app.compliance import observations
    from app.document_desk.models import (
        Document,
        FactRevision,
        VerificationCheck,
        VerificationResult,
        Version,
    )

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        previous = db.scalar(
            select(VerificationResult)
            .join(VerificationCheck)
            .where(VerificationCheck.check_type == "IRN_LIVE_STATUS")
        )
        check = db.get(VerificationCheck, previous.verification_check_id)
        captured = db.get(FactRevision, check.fact_revision_id)
        doc = db.get(Document, db.get(Version, captured.document_version_id).document_id)
        data = previous.result_json["normalised_result"]
        failed = demo.observations(
            db,
            demo.actor(db, fx, "seller-operations"),
            doc,
            captured.canonical_document_json,
            data,
            "IRN_LIVE_STATUS",
            {"lookup_outcome": outcome},
        )
        row = rebind(db, fx, cn, {"verification_result_ids": [failed.id]})
        value, _, dimensions = observations.observation(
            db,
            db.get(Binding, row["id"]),
            "IRN_LIVE_STATUS",
            {"identifier": data["identifier"]},
            {"policy": "SIMULATED_ONLY", "maximum_age_seconds": 900},
            now(),
            "SIMULATION",
        )
        assert value is None
        assert any(d["lookup_outcome"] == outcome for d in dimensions)


@pytest.mark.parametrize(
    "policy,expected",
    [("AUTHORISED_LIVE_ONLY", None), ("AUTHORISED_LIVE_OR_REVIEWED_MANUAL", True)],
)
def test_manual_proof_requires_explicit_policy_and_independent_review(fixture, policy, expected):
    from app.compliance import observations
    from app.document_desk import verification
    from app.document_desk.models import Document, FactRevision
    from app.document_desk.schemas import ManualAttestation
    from app.trades.models import Trade

    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        source = db.get(
            Binding,
            context.heads(db, db.get(demo.Consignment, cn["id"])).current_binding_revision_id,
        )
        doc = db.get(Document, source.binding_json["movement_document"]["document_id"])
        data = db.get(FactRevision, doc.effective_fact_revision_id).canonical_document_json
        irn = data["header"]["irn"]
        preparer = demo.actor(db, fx, "seller-operations")
        asset = demo.attachment(
            db,
            preparer,
            db.get(Trade, fx["trade_id"]),
            None,
            "simulated-portal-observation.pdf",
            demo.pdf("SIMULATION portal observation"),
            purpose="OTHER",
        )
        manual = verification.manual(
            db,
            preparer,
            doc.current_version_id,
            ManualAttestation(
                check_type="IRN_LIVE_STATUS",
                target_identifier=irn,
                portal_source_url="https://einvoice.gst.gov.in/",
                observed_at=now(),
                observed_status="ACTIVE",
                observed_fields={"identifier": irn, "status": "ACTIVE"},
                evidence_attachment_ids=[asset.id],
            ),
        )
        reviews.manual_review(
            db,
            demo.actor(db, fx, "seller-approver"),
            manual["id"],
            DeclarationReview(decision="APPROVE_DECLARATION", reason="Independent portal evidence"),
        )
        bound = rebind(db, fx, cn, {"manual_attestation_ids": [manual["id"]]})
        value, _, dimensions = observations.observation(
            db,
            db.get(Binding, bound["id"]),
            "IRN_LIVE_STATUS",
            {"identifier": irn},
            {"policy": policy, "maximum_age_seconds": 900, "required_observed_fields": ["status"]},
            now(),
            "PRODUCTION",
        )
        assert value is expected
        if expected:
            assert any(d["method"] == "MANUAL_REPORTED" for d in dimensions)


def test_business_document_cannot_be_published_as_a_regulation(fixture):
    from app.compliance.schemas_rules import SourceInput
    from app.operations.models import Attachment

    sessions, fx, _, _, prepared = fixture
    with sessions() as db:
        asset = db.get(Attachment, prepared["invoice_attachment_id"])
        with pytest.raises(TradeError) as error:
            governance.source(
                db,
                demo.actor(db, fx, "seller-operations"),
                None,
                SourceInput(
                    source_kind="RULE",
                    issuer="Not a regulation",
                    title="Invoice masquerading as law",
                    source_status="ACTIVE",
                    official_url="https://gstcouncil.gov.in/",
                    retrieved_at=now(),
                    snapshot_attachment_id=asset.id,
                    source_sha256=asset.sha256,
                    jurisdictions=["IN"],
                    interpretation_note="Must not leak business records into the public registry",
                ),
            )
        assert error.value.code == "FORBIDDEN"
