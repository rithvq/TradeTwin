"""Phase 7 boundaries: exact replay, independent dimensions, recipient checks and fencing."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.compliance.demo import actor  # noqa: E402
from app.document_desk.worker import run_one  # noqa: E402
from app.freight import demo  # noqa: E402
from app.freight.models import Commitment, Run  # noqa: E402
from app.product import (  # noqa: E402
    assurance,
    bundles,
    fence,
    rehearsal,  # noqa: E402
    replay,
    tasks,
    workspace,
)
from app.product import demo as guided_demo  # noqa: E402
from app.product import schemas as s  # noqa: E402
from app.product.models import CheckResult, ReplayRequest, ReplayResult  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Grant, Membership, Trade, now  # noqa: E402


@pytest.fixture()
def fx(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADETWIN_OPERATIONAL_FENCE_FILE", raising=False)
    monkeypatch.delenv("TRADETWIN_REQUIRE_QUALIFICATION", raising=False)
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'product.db'}")
    schema = f"product_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        if not url:
            connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine)
    sessions = sessionmaker(engine)
    data = demo.seed(sessions, "product-integration")
    monkeypatch.setenv("TRADETWIN_CONTROL_ORGANISATION_IDS", data["organizations"]["seller"])
    with sessions() as db:
        job_id = db.get(Run, data["run_id"]).job_id
    assert run_one(sessions, job_id)
    try:
        yield sessions, data
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def grant(db, ctx, *permissions):
    member = db.scalar(
        select(Membership).where(
            Membership.user_id == ctx.user.id, Membership.organization_id == ctx.org_id
        )
    )
    for code in permissions:
        db.add(
            Grant(
                membership_id=member.id,
                permission_code=code,
                capability="EVIDENCE_ANALYST",
                created_by=ctx.user.id,
            )
        )
    db.flush()


def test_workspace_preserves_dimensions_and_redacts_finance(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        value = workspace.read(db, ctx, data["trade_id"])
        s.WorkspaceView.model_validate(value)
        assert value["commercial"]["agreement_status"] == "CONFIRMED"
        assert "completed_percent" not in value
        assert "goods_finance" not in value
        assert value["fulfilment"]["ordered_lines"]
        assert all(line["uqc"] for line in value["fulfilment"]["ordered_lines"])
        assert value["consignments"][0]["historical_authorisation_coverage"] == "NOT_APPLICABLE"


def test_task_seen_is_not_approval_and_blocker_cannot_snooze(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        value = workspace.read(db, ctx, data["trade_id"])
        task = value["tasks"][0]
        result = tasks.change(
            db,
            ctx,
            data["trade_id"],
            s.TaskCommand(
                task_key=task["task_key"],
                task_basis_hash=task["basis_hash"],
                operation="SEEN",
                reason="Read",
            ),
        )
        assert result["business_action_completed"] is False
        assert db.get(Trade, data["trade_id"]).agreement_status == "CONFIRMED"
        if task["priority"] == "BLOCKER":
            with pytest.raises(TradeError, match="snoozed"):
                tasks.change(
                    db,
                    ctx,
                    data["trade_id"],
                    s.TaskCommand(
                        task_key=task["task_key"],
                        task_basis_hash=task["basis_hash"],
                        operation="SNOOZE",
                        snoozed_until=now() + timedelta(hours=1),
                        reason="Later",
                    ),
                )
        with pytest.raises(TradeError):
            tasks.change(
                db,
                ctx,
                data["trade_id"],
                s.TaskCommand(
                    task_key=task["task_key"],
                    task_basis_hash="0" * 64,
                    operation="SEEN",
                    reason="Stale",
                ),
            )


def test_recompute_exact_inputs_and_no_business_writes(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "evidence.replay.request")
        run = db.get(Run, data["run_id"])
        before = db.get(Trade, data["trade_id"]).row_version
        queued = replay.request(
            db,
            ctx,
            None,
            s.ReplayInput(
                subject_type="TRADETWIN_RUN",
                subject_id=run.id,
                replay_kind="RECOMPUTE_CAPTURED_INPUTS",
                source_manifest_hash=run.content_hash,
                expected_engine_version=run.engine_version,
            ),
        )
        job = db.get(ReplayRequest, queued["id"]).job_id
        db.commit()
    assert run_one(sessions, job)
    with sessions() as db:
        value = replay.read(db, actor(db, data, "seller-operations"), queued["id"])
        assert value["input_integrity"] == "PASS"
        assert value["recomputation"] == "MATCH"
        assert value["current_readiness"] == "NOT_ASSESSED_BY_REPLAY"
        assert db.get(Trade, data["trade_id"]).row_version == before
        assert not list(db.scalars(select(Commitment)))
        with pytest.raises(TradeError):
            replay.read(db, actor(db, data, "buyer-receiver"), queued["id"])


def test_replay_revoked_permission_denies_download(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "evidence.replay.request")
        run = db.get(Run, data["run_id"])
        queued = replay.request(
            db,
            ctx,
            None,
            s.ReplayInput(
                subject_type="TRADETWIN_RUN",
                subject_id=run.id,
                replay_kind="RECOMPUTE_CAPTURED_INPUTS",
                source_manifest_hash=run.content_hash,
                expected_engine_version="UNSUPPORTED",
            ),
        )
        result = replay.complete(db, ctx, queued["id"])
        assert result.result_json["recomputation"] == "UNSUPPORTED_ENGINE"
        for permission in db.scalars(
            select(Grant).where(Grant.permission_code == "evidence.replay.request")
        ):
            permission.revoked_at = now()
        db.flush()
        with pytest.raises(TradeError):
            replay.read(db, ctx, queued["id"])


def test_comparison_has_completed_replays(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "evidence.replay.request")
        run = db.get(Run, data["run_id"])
        ref = {"subject_type": "TRADETWIN_RUN", "subject_id": run.id}
        replay.comparison(
            db,
            ctx,
            None,
            s.ComparisonInput(
                left_subject_reference=ref,
                right_subject_reference=ref,
                expected_manifest_hashes=[run.content_hash] * 2,
            ),
        )
        db.flush()
        assert len(list(db.scalars(select(ReplayResult)))) == 2


def test_bundle_is_recipient_only_no_raw_documents(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "evidence.bundle.request")
        queued = bundles.request(
            db,
            ctx,
            None,
            s.BundleInput(
                subject_type="TRADETWIN_RUN",
                subject_id=data["run_id"],
                visibility="PRIVATE_RECIPIENT",
            ),
        )
        bundles.complete(db, ctx, queued["id"])
        value = bundles.read(db, ctx, queued["id"], True)
        assert value["manifest"]["raw_documents_included"] is False
        assert value["manifest"]["source_payloads_included"] is False
        with pytest.raises(TradeError):
            bundles.request(
                db,
                ctx,
                None,
                s.BundleInput(
                    subject_type="TRADETWIN_RUN",
                    subject_id=data["run_id"],
                    visibility="PUBLIC_SYNTHETIC_DEMO",
                ),
            )


def test_external_fence_and_pause_invalidate_dependencies(fx, tmp_path, monkeypatch):
    sessions, data = fx
    path = tmp_path / "external-fence.json"
    generation = {"deployment_id": str(uuid4()), "generation_id": str(uuid4())}
    path.write_text(json.dumps(generation))
    monkeypatch.setenv("TRADETWIN_OPERATIONAL_FENCE_FILE", str(path))
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "readiness.read", "deployment.pause")
        value = assurance.context(db, ctx)
        before = fence.dependency(db)
        ctx.if_match = value["etag"]
        assurance.pause(
            db,
            ctx,
            generation["deployment_id"],
            s.PauseInput(
                reason="Incident", pause_binding_actions=True, pause_movement_permissions=True
            ),
        )
        assert before != fence.dependency(db)
        with pytest.raises(TradeError):
            fence.guard(db, db.get(Trade, data["trade_id"]), "MOVEMENT")
        path.write_text(json.dumps({**generation, "generation_id": str(uuid4())}))
        assert (
            assurance.context(db, ctx)["qualification_outcome"] == "RESTORE_RECONCILIATION_REQUIRED"
        )


def test_readiness_unknown_cannot_be_qualified(fx, tmp_path, monkeypatch):
    sessions, data = fx
    path = tmp_path / "fence.json"
    path.write_text(json.dumps({"deployment_id": str(uuid4()), "generation_id": str(uuid4())}))
    monkeypatch.setenv("TRADETWIN_OPERATIONAL_FENCE_FILE", str(path))
    with sessions() as db:
        operator = actor(db, data, "seller-operations")
        reviewer = actor(db, data, "seller-approver")
        grant(db, operator, "readiness.read", "readiness.run")
        grant(db, reviewer, "readiness.read", "readiness.review")
        value = assurance.context(db, operator)
        queued = assurance.enqueue(
            db,
            operator,
            None,
            s.RunInput(
                expected_manifest_hash=value["manifest_hash"], check_suite_code=assurance.SUITE
            ),
        )
        assurance.complete(db, operator, queued["id"])
        result = assurance.read(db, reviewer, queued["id"])
        assert result["qualification_outcome"] == "NOT_QUALIFIED"
        assert {c["outcome"] for c in result["checks"]} == {"FAIL", "UNKNOWN"}
        with pytest.raises(TradeError):
            assurance.qualify(
                db,
                reviewer,
                queued["id"],
                s.QualificationInput(
                    result_hash=result["result_hash"],
                    decision="APPROVE_QUALIFICATION",
                    reason="Cannot override",
                ),
            )
        db.commit()
    with sessions() as db:
        check = db.scalar(select(CheckResult))
        check.outcome = "PASS"
        with pytest.raises(DBAPIError):
            db.flush()


def test_client_cannot_supply_outcomes_or_actor():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        s.RunInput(
            expected_manifest_hash="a" * 64, check_suite_code=assurance.SUITE, outcome="PASS"
        )
    with pytest.raises(ValidationError):
        s.ReplayInput(
            subject_type="TRADETWIN_RUN",
            subject_id=uuid4(),
            replay_kind="RECORDED_DECISION",
            source_manifest_hash="a" * 64,
            expected_engine_version="X",
            actor_id=uuid4(),
        )


def test_demo_runs_as_current_principal_and_reset_preserves_history(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "demo.read", "demo.workspace.create", "demo.run", "demo.clock.advance")
        created = guided_demo.create(
            db, ctx, None, s.DemoCreate(scenario_code="BOUNDED_JOURNEY_V1")
        )
        assert created["trade_id"] is None
        ctx.if_match = created["etag"]
        run = guided_demo.start(
            db,
            ctx,
            created["id"],
            s.DemoRunInput(scenario_manifest_hash=created["scenario_manifest_hash"]),
        )
        for code in (
            "CREATE_SIMULATION_DRAFT",
            "READ_INDEPENDENT_DIMENSIONS",
            "EXECUTABLE_RECOVERY",
        ):
            ctx.if_match = run["etag"]
            run = guided_demo.step(db, ctx, run["id"], s.DemoStep(step_code=code))
        assert run["status"] == "BLOCKED"
        trade = db.get(Trade, run["trade_id"])
        assert trade.agreement_status == "DRAFT"
        assert trade.execution_mode == "SIMULATION"
        assert all(receipt["principal_user_id"] == ctx.user.id for receipt in run["receipts"])
        ctx.if_match = run["workspace_etag"]
        successor = guided_demo.reset(
            db, ctx, created["id"], s.DemoCreate(scenario_code="BOUNDED_JOURNEY_V1")
        )
        assert successor["id"] != created["id"] and successor["trade_id"] is None
        assert guided_demo.read(db, ctx, created["id"])["state"] == "SEALED"
        assert guided_demo.run_view(db, ctx, run["id"])["receipts"]
        with pytest.raises(TradeError):
            fence.guard(db, trade, "MOVEMENT")


def test_virtual_demo_clock_does_not_change_real_permissions(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "demo.read", "demo.workspace.create", "demo.clock.advance")
        created = guided_demo.create(
            db, ctx, None, s.DemoCreate(scenario_code="BOUNDED_JOURNEY_V1")
        )
        ctx.if_match = created["etag"]
        before = now()
        advanced = guided_demo.advance(
            db,
            ctx,
            created["id"],
            s.ClockAdvance(advance_seconds=86400, reason="Demonstration timing"),
        )
        assert advanced["virtual_as_of"] != created["virtual_as_of"]
        assert (now() - before).total_seconds() < 10
        assert advanced["business_clock"] == "REAL_SERVER_TIME"
        with pytest.raises(ValidationError):
            s.ClockAdvance(advance_seconds=-1, reason="Reverse")


def test_registered_restore_drill_is_not_production_restore(fx, tmp_path, monkeypatch):
    sessions, data = fx
    path = tmp_path / "drill-fence.json"
    path.write_text(json.dumps({"deployment_id": str(uuid4()), "generation_id": str(uuid4())}))
    monkeypatch.setenv("TRADETWIN_OPERATIONAL_FENCE_FILE", str(path))
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "readiness.read", "deployment.restore.rehearse")
        current = assurance.context(db, ctx)
        before = fence.external()
        result = rehearsal.run(
            db,
            ctx,
            current["deployment_id"],
            s.RestoreInput(registered_rehearsal_profile_code="ISOLATED_SQLITE_FENCE_V1"),
        )
        assert result["outcome"] == "PASS"
        assert result["production_restored"] is False
        assert result["production_rpo_seconds"] is None
        assert fence.external() == before


def test_workspace_http_is_private_and_authenticated(fx):
    from app.database import get_db
    from app.trades.errors import install_handlers
    from app.trades.router import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tradetwin_security import identity

    sessions, data = fx
    app = FastAPI()
    app.include_router(router)
    install_handlers(app)

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency

    @app.middleware("http")
    async def principal(request, call_next):
        subject = data["subjects"].get(request.headers.get("X-Test-User"))
        token = identity.set({"id": subject} if subject else None)
        try:
            return await call_next(request)
        finally:
            identity.reset(token)

    with TestClient(app) as client:
        path = f"/api/v1/trades/{data['trade_id']}/workspace"
        headers = {
            "X-Test-User": "seller-operations",
            "X-Organization-Id": data["organizations"]["seller"],
        }
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert "no-store" in response.headers["Cache-Control"]
        assert "goods_finance" not in response.json()
        assert client.get(path).status_code in {401, 403}


def test_revoked_requester_cannot_publish_a_worker_result(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        grant(db, ctx, "evidence.replay.request")
        run = db.get(Run, data["run_id"])
        queued = replay.request(
            db,
            ctx,
            None,
            s.ReplayInput(
                subject_type="TRADETWIN_RUN",
                subject_id=run.id,
                replay_kind="RECORDED_DECISION",
                source_manifest_hash=run.content_hash,
                expected_engine_version=run.engine_version,
            ),
        )
        job_id = db.get(ReplayRequest, queued["id"]).job_id
        for permission in db.scalars(
            select(Grant).where(Grant.permission_code == "evidence.replay.request")
        ):
            permission.revoked_at = now()
        db.commit()
    assert run_one(sessions, job_id)
    with sessions() as db:
        assert db.get(ReplayRequest, queued["id"]).job_state == "FAILED"
        assert not db.scalar(select(ReplayResult).where(ReplayResult.request_id == queued["id"]))


def test_production_protection_does_not_become_approval(fx, monkeypatch):
    from app.trades.agreements import create_trade
    from app.trades.schemas import TradeCreate

    sessions, data = fx
    monkeypatch.setenv("TRADETWIN_REQUIRE_QUALIFICATION", "true")
    with sessions() as db:
        ctx = actor(db, data, "seller-operations")
        created = create_trade(db, ctx, TradeCreate(initiated_by_role="SELLER"))
        trade = db.get(Trade, created["trade_id"])
        for action in ("BINDING", "MOVEMENT"):
            with pytest.raises(TradeError) as blocked:
                fence.guard(db, trade, action)
            assert blocked.value.code == "PILOT_NOT_QUALIFIED"
        assert trade.agreement_status == "DRAFT"


def test_tenant_roles_cannot_escalate_into_global_deployment_controls(fx):
    sessions, data = fx
    with sessions() as db:
        ctx = actor(db, data, "buyer-receiver")
        grant(db, ctx, "readiness.read", "readiness.run", "deployment.pause")
        for permission in ("readiness.run", "deployment.pause"):
            with pytest.raises(TradeError) as denied:
                assurance.control(db, ctx, permission)
            assert denied.value.code == "OPERATOR_NOT_BOUND"
