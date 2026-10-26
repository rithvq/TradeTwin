"""Projection/gate parity, recipient isolation and actual movement observations."""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from tradetwin_security import ProfileMiddleware, identity

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.compliance import (  # noqa: E402
    authorization_window,
    context,
    dashboard,
    demo,
    evaluations,
    handoff,
    rule_dependencies,
)
from app.compliance.clock import aware, use_test_clock  # noqa: E402
from app.compliance.models import Authorization, Evaluation, Packet, ReleaseReview  # noqa: E402
from app.compliance.models_dashboard import (  # noqa: E402
    AuthorizationWindow,
    EvidenceChangeBaseline,
)
from app.compliance.schemas_dashboard import (  # noqa: E402
    DispatchDashboardView,
    DispatchJourneyView,
)
from app.compliance.schemas_facts import EvaluationInput  # noqa: E402
from app.database import get_db  # noqa: E402
from app.document_desk.models import (  # noqa: E402
    Document,
    FactRevision,
    VerificationCheck,
    VerificationResult,
    Version,
)
from app.operations import movement  # noqa: E402
from app.operations.cli import Demo  # noqa: E402
from app.operations.demo import seed_demo  # noqa: E402
from app.operations.models import Assignment, Consignment, Event  # noqa: E402
from app.operations.schemas import ShipmentEventInput  # noqa: E402
from app.trades.errors import TradeError, install_handlers  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Audit, Grant, now, uid  # noqa: E402
from app.trades.router import router  # noqa: E402


@pytest.fixture()
def fixture(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    schema = "dashboard_test_" + uid().replace("-", "") if url else None
    engine = create_engine(
        url or f"sqlite:///{tmp_path / 'dashboard.db'}",
        connect_args={} if url else {"check_same_thread": False},
    )
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
            fx = seed_demo(db, namespace="dispatch-dashboard")
        harness = Demo(sessions, fx)
        cn = harness.allocate("50")
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


def pickup(cn, assignment, prepared, token):
    return {
        "client_event_id": uid(),
        "event_type": "PICKUP_CONFIRMED",
        "assignment_id": assignment["id"],
        "dispatch_authorization_id": token["id"],
        "loading_manifest_revision_id": prepared["manifest_id"],
        "occurred_at": now().isoformat(),
        "payload": {
            "actual_gross_weight_kg": "400",
            "actual_package_count": 4,
            "items": [
                {
                    "consignment_item_id": i["id"],
                    "loaded_quantity": str(i["allocated_quantity"]),
                    "uqc": i["uqc"],
                }
                for i in cn["items"]
            ],
        },
    }


def test_projection_matches_gate_and_contains_only_safe_summary(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        actor = demo.actor(db, fx, "seller-operations")
        gate = handoff.readiness(db, actor, cn["id"], "PICKUP_CONFIRMED")
        value = dashboard.listing(db, actor)
        DispatchDashboardView.model_validate(value)
        assert value["counts"]["ready_to_move"] == 1
        assert value["items"][0]["readiness_state"] == gate["state"] == "READY"
        journey = dashboard.journey(db, actor, cn["id"], "PICKUP_CONFIRMED")
        DispatchJourneyView.model_validate(journey)
        assert [s["number"] for s in journey["stages"]] == list(range(1, 8))
        assert journey["stages"][4]["facts"]["authorization_id"] == token["id"]
        assert journey["stages"][5]["status"] == "PENDING"
        assert journey["stages"][2]["facts"]["rules_reused"] == 0
        wire = json.dumps(journey)
        assert not re.search(r'"[a-f0-9]{64}"', wire)
        assert "matching_revisions" not in wire and "source_reference_json" not in wire
        departure = dashboard.journey(db, actor, cn["id"], "DEPARTED")
        assert departure["stages"][4]["status"] == "NOT_ISSUED"
        assert db.get(Authorization, token["id"]).consumed_event_id is None


def test_membership_driver_and_permission_revocation(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        unrelated = demo.actor(db, fx, "unrelated")
        unrelated.org_id = fx["organizations"]["unrelated"]
        assert dashboard.listing(db, unrelated)["items"] == []
        with pytest.raises(TradeError):
            dashboard.journey(db, unrelated, cn["id"], "PICKUP_CONFIRMED")
        assert dashboard.listing(db, demo.actor(db, fx, "driver-two"))["items"] == []
        current = demo.actor(db, fx, "driver-one")
        assert dashboard.listing(db, current)["total"] == 1
        for grant in db.scalars(select(Grant).where(Grant.permission_code == "compliance.read")):
            grant.revoked_at = now()
        db.flush()
        assert dashboard.listing(db, current)["items"] == []


def test_vehicle_assignment_change_makes_old_authorization_unusable(fixture):
    sessions, fx, cn, assignment, _ = fixture
    with sessions() as db:
        demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        row = db.get(Assignment, assignment["id"])
        row.vehicle_snapshot = {**row.vehicle_snapshot, "registration_number": "KA01ZZ9999"}
        db.flush()
        actor = demo.actor(db, fx, "seller-operations")
        view = dashboard.journey(db, actor, cn["id"], "PICKUP_CONFIRMED")
        assert view["readiness_state"] != "READY"
        assert view["stages"][4]["status"] == "UNUSABLE"
        assert dashboard.listing(db, actor)["counts"]["ready_to_move"] == 0


def test_expiry_and_expiring_counts_use_server_time(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        expiry = aware(db.get(Authorization, token["id"]).expires_at)
        db.commit()
    with use_test_clock(lambda: expiry - timedelta(seconds=1)), sessions() as db:
        assert (
            dashboard.listing(db, demo.actor(db, fx, "seller-operations"))["counts"][
                "expiring_soon"
            ]
            == 1
        )
    with use_test_clock(lambda: expiry), sessions() as db:
        actor = demo.actor(db, fx, "seller-operations")
        assert dashboard.listing(db, actor)["counts"]["ready_to_move"] == 0
        assert (
            dashboard.journey(db, actor, cn["id"], "PICKUP_CONFIRMED")["stages"][4]["status"]
            == "EXPIRED"
        )


def test_actual_quantity_rejection_is_retained_after_rollback_then_success(fixture):
    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
    app = FastAPI()
    install_handlers(app)
    app.include_router(router)

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    principal = identity.set({"id": fx["subjects"]["driver-one"]})
    try:
        with TestClient(app) as client:
            payload = pickup(cn, assignment, prepared, token)
            payload["payload"]["items"][0]["loaded_quantity"] = "1"
            headers = {
                "X-Organization-Id": fx["organizations"]["carrier"],
                "Idempotency-Key": uid(),
            }
            response = client.post(
                f"/api/v1/consignments/{cn['id']}/events", json=payload, headers=headers
            )
            assert response.status_code == 409, response.text
            reason = response.json()["error"]["code"]
            with sessions() as db:
                view = dashboard.journey(
                    db, demo.actor(db, fx, "driver-one"), cn["id"], "PICKUP_CONFIRMED"
                )
                assert view["stages"][5]["status"] == "REJECTED"
                assert view["stages"][6]["reason_codes"] == [reason]
                assert db.get(Authorization, token["id"]).consumed_event_id is None
                assert db.scalar(select(Event)) is None
                audit = db.scalar(select(Audit).where(Audit.action == "DISPATCH_MOVEMENT_REJECTED"))
                assert "payload" not in audit.redacted_summary_json
            response = client.post(
                f"/api/v1/consignments/{cn['id']}/events",
                json=pickup(cn, assignment, prepared, token),
                headers={**headers, "Idempotency-Key": uid()},
            )
            assert response.status_code == 201, response.text
    finally:
        identity.reset(principal)
    with sessions() as db:
        actor = demo.actor(db, fx, "seller-operations")
        view = dashboard.journey(db, actor, cn["id"], "PICKUP_CONFIRMED")
        assert view["stages"][5]["status"] == "PASSED"
        assert view["stages"][6]["facts"]["consumed_authorization_id"] == token["id"]
        assert view["stages"][4]["status"] == "CONSUMED"
        assert (
            dashboard.journey(db, actor, cn["id"], "DEPARTED")["stages"][5]["status"] == "PENDING"
        )


def test_postgresql_duplicate_attempts_have_one_recorded_journey(fixture):
    sessions, fx, cn, assignment, prepared = fixture
    if sessions.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Requires disposable PostgreSQL")
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
    payload = ShipmentEventInput.model_validate(pickup(cn, assignment, prepared, token))
    barrier = Barrier(2)

    def consume(_):
        barrier.wait(timeout=10)
        with sessions() as db:
            result = movement.event(db, demo.actor(db, fx, "driver-one"), cn["id"], payload)
            db.commit()
            return result["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, [0, 1]))
    assert results[0] == results[1]
    with sessions() as db:
        view = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert view["stages"][6]["facts"]["movement_event_id"] == results[0]
        assert (
            len(list(db.scalars(select(Event).where(Event.event_type == "PICKUP_CONFIRMED")))) == 1
        )


def test_pagination_counts_cover_all_authorized_consignments(fixture):
    sessions, fx, cn, *_ = fixture
    extra = Demo(sessions, fx).allocate("50")
    with sessions() as db:
        actor = demo.actor(db, fx, "seller-operations")
        first = dashboard.listing(db, actor, limit=1)
        assert first["total"] == 2 and len(first["items"]) == 1
        assert first["counts"]["awaiting_evidence_or_review"] == 2
        second = dashboard.listing(db, actor, cursor=first["next_cursor"], limit=1)
        assert second["counts"] == first["counts"]
        assert {first["items"][0]["consignment_id"], second["items"][0]["consignment_id"]} == {
            cn["id"],
            extra["id"],
        }
        assert second["next_cursor"] is None


def test_shadow_reuse_is_not_reported_as_authoritative_reuse(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "FULL")
        demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "SHADOW")
        demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        value = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert value["stages"][2]["facts"]["strategy"] == "FULL"
        assert value["stages"][2]["facts"]["rules_reused"] == 0


def test_legacy_movement_is_not_fabricated_as_a_passed_guard_check(fixture):
    sessions, fx, cn, assignment, _ = fixture
    with sessions() as db:
        db.add(
            Event(
                consignment_id=cn["id"],
                assignment_id=assignment["id"],
                client_event_id=uid(),
                request_hash="0" * 64,
                event_type="PICKUP_CONFIRMED",
                occurred_at=now(),
                recorded_by_user_id=fx["users"]["driver-one"],
                recorded_by_organization_id=fx["organizations"]["carrier"],
                payload_json={},
                execution_mode="SIMULATION",
            )
        )
        row = db.get(Consignment, cn["id"])
        row.phase4_legacy_movement, row.movement_status = True, "PICKED_UP"
        db.commit()
        value = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert value["stages"][5]["status"] == "NOT_RECORDED"
        assert value["stages"][6]["status"] == "RECORDED"
        assert value["stages"][6]["facts"]["consumed_authorization_id"] is None


def evaluate(db, fx, cn):
    actor = demo.actor(db, fx, "seller-operations")
    version = context.version(db, fx["trade_id"])
    actor.if_match = f'"{version}"'
    queued = evaluations.request(
        db,
        actor,
        cn["id"],
        EvaluationInput(action="PICKUP_CONFIRMED", expected_context_version=version),
    )
    return evaluations.complete(db, actor, queued["evaluation_id"])


def test_proven_empty_search_gains_unreviewed_match_without_private_disclosure(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        actor = demo.actor(db, fx, "seller-operations")
        doc = Document(
            trade_id=fx["trade_id"],
            document_type="CARGO_INSURANCE",
            label="Private unreviewed candidate",
            owner_organization_id=actor.org_id,
            execution_mode="SIMULATION",
            created_by=actor.user.id,
        )
        db.add(doc)
        db.commit()
        before = dashboard.journey(db, actor, cn["id"], "PICKUP_CONFIRMED")
        assert before["evidence_changes"]["transitions"] == [
            {
                "document_type": "CARGO_INSURANCE",
                "basis": "SINCE_EVALUATION",
                "code": "EMPTY_SEARCH_GAINED_MATCH",
            }
        ]
        assert "not accepted evidence" in before["evidence_changes"]["notice"]
        assert doc.id not in json.dumps(before)
        buyer = dashboard.journey(
            db, demo.actor(db, fx, "buyer-receiver"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert buyer["evidence_changes"]["transitions"] == []
        fresh = evaluate(db, fx, cn)
        db.commit()
        after = dashboard.journey(db, actor, cn["id"], "PICKUP_CONFIRMED")
        assert after["evidence_changes"]["transitions"][0]["basis"] == "BETWEEN_EVALUATIONS"
        assert doc.id not in json.dumps(fresh.snapshot_json["transport"])
        assert all(
            db.scalar(select(model).where(model.evaluation_id == fresh.id)) is None
            for model in (ReleaseReview, Packet, Authorization)
        )


@pytest.mark.parametrize("after_departure", [False, True])
def test_new_adverse_result_explains_staleness_without_returning_verification_payload(
    fixture, after_departure
):
    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        recorded = None
        action = "PICKUP_CONFIRMED"
        if after_departure:
            movement.event(
                db,
                demo.actor(db, fx, "driver-one"),
                cn["id"],
                ShipmentEventInput.model_validate(pickup(cn, assignment, prepared, token)),
            )
            db.commit()
            token = demo.authorise(db, fx, cn["id"], "DEPARTED")
            db.commit()
            action = "DEPARTED"
            recorded = movement.event(
                db,
                demo.actor(db, fx, "driver-one"),
                cn["id"],
                ShipmentEventInput.model_validate(
                    {
                        "client_event_id": uid(),
                        "event_type": action,
                        "assignment_id": assignment["id"],
                        "dispatch_authorization_id": token["id"],
                        "occurred_at": now(),
                        "payload": {},
                    }
                ),
            )
            db.commit()
        prior = db.scalar(
            select(VerificationResult)
            .join(VerificationCheck)
            .where(VerificationCheck.check_type == "EWB_AUTHORITY_LOOKUP")
        )
        check = db.get(VerificationCheck, prior.verification_check_id)
        fact = db.get(FactRevision, check.fact_revision_id)
        document = db.get(Document, db.get(Version, fact.document_version_id).document_id)
        data = {
            **deepcopy(prior.result_json["normalised_result"]),
            "status": "CANCELLED",
            "private_test_value": "DO_NOT_EXPOSE",
        }
        demo.observations(
            db,
            demo.actor(db, fx, "seller-operations"),
            document,
            fact.canonical_document_json,
            data,
            "EWB_AUTHORITY_LOOKUP",
        )
        db.commit()
        value = dashboard.journey(db, demo.actor(db, fx, "seller-operations"), cn["id"], action)
        assert value["evidence_changes"]["status"] == "STALE"
        assert "NEW_ADVERSE_VERIFICATION_RESULT" in value["evidence_changes"]["reason_codes"]
        assert value["readiness_state"] != "READY"
        assert "DO_NOT_EXPOSE" not in json.dumps(value) and "normalised_result" not in json.dumps(
            value
        )
        if after_departure:
            assert value["stages"][4]["status"] == "CONSUMED"
            assert value["stages"][6]["facts"]["movement_event_id"] == recorded["id"]
            assert "ADVERSE_PROOF_AFTER_DISPATCH" in {
                a["code"] for a in value["post_dispatch_alerts"]
            }


def test_fresh_incremental_evaluation_does_not_bind_old_release_chain(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    monkeypatch.setenv("COMPLIANCE_EVALUATION_MODE", "INCREMENTAL")
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        fresh = evaluate(db, fx, cn)
        db.commit()
        value = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert value["calculation"]["evaluation_id"] == fresh.id != token["evaluation_id"]
        assert value["calculation"]["rules_reused"] > 0
        assert value["calculation"]["authoritative_strategy"] == "INCREMENTAL"
        assert value["calculation"]["permission_reused"] is False
        # The existing gate can still accept the older authorization for its own
        # unchanged evaluation. The projection must not invent revocation or bind
        # that earlier permission to this fresh evaluation.
        assert (
            value["readiness_state"]
            == handoff.readiness(
                db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
            )["state"]
        )
        assert value["stages"][4]["facts"]["evaluation_id"] == token["evaluation_id"]
        assert all(
            i["status"] == "CHANGED"
            for i in value["binding"]["items"]
            if i["label"]
            in {"Evaluation", "Reviewer approval", "Dispatch packet", "Driver acknowledgment"}
        )
        assert all(
            db.scalar(select(model).where(model.evaluation_id == fresh.id)) is None
            for model in (ReleaseReview, Packet, Authorization)
        )
        monkeypatch.setattr(
            rule_dependencies, "engine_manifest", lambda: {"engine_version": "changed-test-engine"}
        )
        changed = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert "ENGINE_VERSION_CHANGED" in changed["evidence_changes"]["reason_codes"]
        newer = evaluate(db, fx, cn)
        db.commit()
        changed = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert changed["calculation"]["evaluation_id"] == newer.id
        assert changed["calculation"]["rules_reused"] == 0


def test_recorded_window_keeps_actual_limiting_permission_and_exclusive_expiry(fixture):
    sessions, fx, cn, assignment, prepared = fixture
    deadline = now() + timedelta(seconds=45)
    with sessions() as db:
        for grant in db.scalars(
            select(Grant).where(Grant.permission_code == "shipment.event.record")
        ):
            grant.expires_at = deadline
        db.flush()
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        row = db.get(Authorization, token["id"])
        window = authorization_window.read(db, row)
        assert window["detail_status"] == "RECORDED"
        assert window["expiry_limited_by"] == ["DRIVER_MOVEMENT_PERMISSION"]
        assert aware(row.expires_at) == deadline
        assert min(aware(dashboard.timestamp(i["at"])) for i in window["expiry_inputs"]) == deadline
        for grant in db.scalars(
            select(Grant).where(Grant.permission_code == "shipment.event.record")
        ):
            grant.expires_at = deadline + timedelta(hours=1)
        db.commit()
        assert authorization_window.read(db, row) == window
    with use_test_clock(lambda: deadline), sessions() as db:
        counts = dashboard.listing(db, demo.actor(db, fx, "seller-operations"))["counts"]
        assert counts["ready_to_move"] == 0 and counts["blocked"] == 1
        view = dashboard.journey(
            db, demo.actor(db, fx, "seller-operations"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert view["stages"][4]["status"] == "EXPIRED"
        with pytest.raises(TradeError) as caught:
            movement.event(
                db,
                demo.actor(db, fx, "driver-one"),
                cn["id"],
                ShipmentEventInput.model_validate(pickup(cn, assignment, prepared, token)),
            )
        assert caught.value.code == "AUTHORISATION_EXPIRED"
        db.rollback()
        assert db.scalar(select(Event)) is None


def test_explanation_rows_are_immutable_and_legacy_detail_is_not_reconstructed(fixture):
    sessions, fx, cn, *_ = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
        for model in (AuthorizationWindow, EvidenceChangeBaseline):
            row = db.scalar(select(model))
            with pytest.raises(DBAPIError), db.begin_nested():
                db.execute(
                    update(model)
                    .where(model.id == row.id)
                    .values(summary_json={"fabricated": True})
                )
        original = db.get(Authorization, token["id"])
        legacy = Authorization(
            **{
                c.name: getattr(original, c.name)
                for c in Authorization.__table__.columns
                if c.name not in {"id", "created_at"}
            }
        )
        db.add(legacy)
        db.flush()
        detail = authorization_window.read(db, legacy)
        assert detail == {"detail_status": "NOT_RECORDED", "notice": "Detail not recorded."}
        prior = db.get(Evaluation, token["evaluation_id"])
        older = Evaluation(
            **{
                c.name: getattr(prior, c.name)
                for c in Evaluation.__table__.columns
                if c.name not in {"id", "created_at"}
            }
        )
        db.add(older)
        db.flush()
        from app.compliance import evidence_changes

        view = evidence_changes.read(
            db,
            demo.actor(db, fx, "seller-operations"),
            older,
            db.get(demo.Trade, fx["trade_id"]),
            db.get(Consignment, cn["id"]),
            "CURRENT",
            now(),
        )
        assert view["detail_status"] == "NOT_RECORDED" and view["transitions"] == []


def test_authenticated_http_projection_has_private_no_store_and_enforces_org(fixture, monkeypatch):
    sessions, fx, cn, *_ = fixture
    import tradetwin_security

    async def resolve(_token):
        return {"id": fx["subjects"]["seller-operations"]}

    monkeypatch.setenv("PROFILE_AUTH_ENABLED", "true")
    monkeypatch.setattr(tradetwin_security, "resolve_identity", resolve)
    app = FastAPI()
    app.add_middleware(ProfileMiddleware)
    install_handlers(app)
    app.include_router(router)

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        headers = {
            "Authorization": "Bearer disposable-test-session",
            "X-Organization-Id": fx["organizations"]["seller"],
        }
        response = client.get("/api/v1/dispatch-dashboard?limit=1", headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.json()["items"][0]["consignment_id"] == cn["id"]
        detail = client.get(f"/api/v1/consignments/{cn['id']}/dispatch-journey", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.headers["Cache-Control"] == "private, no-store"
        assert (
            client.get(
                "/api/v1/dispatch-dashboard",
                headers={**headers, "X-Organization-Id": fx["organizations"]["unrelated"]},
            ).status_code
            == 403
        )
        assert client.get("/api/v1/dispatch-dashboard").status_code == 401
