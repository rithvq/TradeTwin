"""Integrated demo uses domain guards, isolated ownership and ordinary worker jobs."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.compliance import demo as release  # noqa: E402
from app.demo_center import fixtures, scenario, service  # noqa: E402
from app.demo_center.catalog import STEPS  # noqa: E402
from app.demo_center.models import Command, Launch  # noqa: E402
from app.demo_center.router import CreateDemo, Step  # noqa: E402
from app.document_desk import jobs  # noqa: E402
from app.document_desk.models import Job  # noqa: E402
from app.document_desk.worker import complete  # noqa: E402
from app.freight_routes import history  # noqa: E402
from app.freight_routes.models import RouteStudy  # noqa: E402
from app.operations import payments  # noqa: E402
from app.operations.models import Consignment, Event  # noqa: E402
from app.trades import profiles  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Grant, Membership, Trade, User, uid  # noqa: E402
from app.trades.transactions import Context  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("IN_APP_DEMO_ENABLED", "true")
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'demo.db'}")
    schema = "demo_test_" + uuid4().hex if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})

    @event.listens_for(engine, "connect")
    def keys(connection, _):
        if not url:
            connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        owner = User(
            identity_subject="demo-test:" + uid(),
            display_name="Owner",
            email="owner@example.invalid",
        )
        other = User(
            identity_subject="demo-test:" + uid(),
            display_name="Other",
            email="other@example.invalid",
        )
        db.add_all([owner, other])
        db.commit()
        ids = owner.id, other.id
    try:
        yield sessions, ids
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def ctx(db, ident):
    return Context(db.get(User, ident), None, uid())


def test_demo_invoice_resolves_packaged_layout_without_repository_depth(tmp_path, monkeypatch):
    module = tmp_path / "app/app/demo_center/fixtures.py"
    bundled = tmp_path / "app/data/fixtures/document-desk/invoice.pdf"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"%PDF-packaged-simulation")
    monkeypatch.setattr(fixtures, "__file__", str(module))
    monkeypatch.delenv("DOCUMENT_FIXTURE_DIRECTORY", raising=False)
    assert fixtures.invoice() == b"%PDF-packaged-simulation"


def test_configured_demo_invoice_directory_is_honoured(tmp_path, monkeypatch):
    bundled = tmp_path / "invoice.pdf"
    bundled.write_bytes(b"%PDF-configured-simulation")
    monkeypatch.setenv("DOCUMENT_FIXTURE_DIRECTORY", str(tmp_path))
    assert fixtures.invoice() == b"%PDF-configured-simulation"
    monkeypatch.setenv("DOCUMENT_FIXTURE_DIRECTORY", str(tmp_path / "missing"))
    with pytest.raises(TradeError) as error:
        fixtures.invoice()
    assert error.value.code == "DEMO_FIXTURE_UNAVAILABLE"


def create(sessions, owner):
    with sessions() as db:
        value = service.launch(db, ctx(db, owner), CreateDemo())
        db.commit()
        return value["id"]


def claim(sessions, ident):
    with sessions() as db:
        row = db.get(Launch, ident)
        return jobs.claim(db, "test-demo", db.get(Command, row.active_command_id).job_id)


def test_owner_isolation_step_order_and_no_production_permissions(env):
    sessions, (owner, other) = env
    ident = create(sessions, owner)
    assert create(sessions, owner) == ident
    with sessions() as db:
        with pytest.raises(TradeError, match="not found"):
            service.view(db, ctx(db, other), ident)
        assert not list(db.scalars(select(Membership).where(Membership.user_id == owner)))
        with pytest.raises(TradeError):
            service.step(db, ctx(db, owner), ident, Step(step_code="PICKUP"))
        assert not list(db.scalars(select(Trade)))


def test_missing_invoice_fails_before_provisioning_records(env, monkeypatch, tmp_path):
    sessions, (owner, _) = env
    ident = create(sessions, owner)
    lease = claim(sessions, ident)
    monkeypatch.setenv("DOCUMENT_FIXTURE_DIRECTORY", str(tmp_path / "missing"))
    with pytest.raises(TradeError) as error:
        scenario.install(sessions, ident, lease)
    assert error.value.code == "DEMO_FIXTURE_UNAVAILABLE"
    with sessions() as db:
        assert not list(db.scalars(select(Trade)))
        assert not list(db.scalars(select(Membership).where(Membership.user_id == owner)))


def test_full_registered_journey_and_route_memory(env, monkeypatch):
    sessions, (owner, _) = env
    ident = create(sessions, owner)
    original_job = scenario.Scenario.job

    def local_job(self, job_id):
        with sessions() as db:
            job = db.get(Job, job_id)
            if job.stage == "EXTRACT":
                # External encrypted storage/parser are covered by the browser acceptance.
                assert job.request_json["strategy"] == "AUTO"
                return
        original_job(self, job_id)

    monkeypatch.setattr(scenario.Scenario, "job", local_job)

    def metadata(db, c, trade, cn, label, content, purpose):
        return release.attachment(db, c, trade, cn, label, content, purpose=purpose)

    lease = claim(sessions, ident)
    output = scenario.install(sessions, ident, lease, store=metadata)
    with sessions() as db:
        complete(db, lease, output)
        row = db.get(Launch, ident)
        data = row.fixture_json
        cnid = data["consignment_id"]
        assert db.get(Trade, row.trade_id).execution_mode == "SIMULATION"
        assert (
            len(
                history.capture(
                    db,
                    release.actor(db, data, "seller-operations"),
                    "SIMULATION",
                    scenario.instant(db),
                )
            )
            == 3
        )
        assert len(data["route_study_ids"]) == 2
        assert all(db.get(RouteStudy, s).result_json for s in data["route_study_ids"])
        grants = list(db.scalars(select(Grant).join(Membership).where(Membership.user_id == owner)))
        assert grants and not {g.permission_code for g in grants} & {
            "order.confirm.seller",
            "order.confirm.buyer",
            "shipment.event.record",
            "members.manage",
            "freight.commit.approve",
            "dispatch.release.approve",
            "dispatch.authorisation.request",
            "routing.dataset.publish",
        }
        assert all(
            "appdemo" not in p["legal_name"] for p in profiles.trading_partners(db, "appdemo")
        )
    for step in STEPS:
        with sessions() as db:
            service.step(db, ctx(db, owner), ident, Step(step_code=step["code"]))
            db.commit()
        lease = claim(sessions, ident)
        output = scenario.execute(sessions, ident, step["code"], lease)
        with sessions() as db:
            complete(db, lease, output)
    with sessions() as db:
        view = service.view(db, ctx(db, owner), ident)
        assert view["next_step_index"] == len(STEPS)
        assert db.get(Consignment, cnid).movement_status == "DELIVERY_CLOSED"
        events = list(db.scalars(select(Event).where(Event.consignment_id == cnid)))
        assert {e.event_type for e in events} == {"PICKUP_CONFIRMED", "DEPARTED", "ARRIVED"}
        assert len(events) == 3
        reader = ctx(db, owner)
        reader.org_id = data["organizations"]["seller"]
        settlement = payments.settlement(db, reader, db.get(Trade, data["trade_id"]))
        assert settlement["reported_payment_minor"] == "1000000"
        assert settlement["allowed_actions"] == []
        assert all(
            j.status == "SUCCEEDED"
            for j in db.scalars(select(Job).where(Job.stage == "EVAL_COMPLIANCE"))
        )
        with pytest.raises(TradeError):
            service.step(db, ctx(db, owner), ident, Step(step_code="PICKUP"))
        fresh = service.launch(db, ctx(db, owner), CreateDemo(fresh=True))
        assert fresh["id"] != ident and fresh["predecessor_id"] == ident
        assert db.get(Consignment, cnid).movement_status == "DELIVERY_CLOSED"


def test_disabled_and_revoked_owner_fail_closed(env, monkeypatch):
    sessions, (owner, _) = env
    ident = create(sessions, owner)
    lease = claim(sessions, ident)
    with sessions() as db:
        db.get(User, owner).active = False
        db.commit()
    with sessions() as db:
        with pytest.raises(TradeError):
            scenario.Scenario(sessions, ident, lease).guard(db)
    monkeypatch.setenv("IN_APP_DEMO_ENABLED", "false")
    with sessions() as db, pytest.raises(TradeError):
        service.launch(db, ctx(db, owner), CreateDemo())


def test_expired_demo_is_readable_but_requires_a_fresh_session(env):
    sessions, (owner, _) = env
    ident = create(sessions, owner)
    with sessions() as db:
        row = db.get(Launch, ident)
        row.status = "READY"
        row.created_at = scenario.instant(db) - timedelta(minutes=11)
        db.commit()
        assert service.view(db, ctx(db, owner), ident)["expired"]
        with pytest.raises(TradeError) as error:
            service.step(db, ctx(db, owner), ident, Step(step_code=STEPS[0]["code"]))
        assert error.value.code == "DEMO_EVIDENCE_EXPIRED"
        assert service.launch(db, ctx(db, owner), CreateDemo())["id"] != ident


def test_lease_failure_is_terminal_and_does_not_repeat_partial_setup(env):
    sessions, (owner, _) = env
    ident = create(sessions, owner)
    lease = claim(sessions, ident)
    with sessions() as db:
        jobs.failed(db, lease, "STORAGE_UNAVAILABLE")
    assert claim(sessions, ident) is None
    with sessions() as db:
        value = service.view(db, ctx(db, owner), ident)
        assert value["status"] == "FAILED"
        assert value["receipts"][0]["error_code"] == "STORAGE_UNAVAILABLE"
        assert service.launch(db, ctx(db, owner), CreateDemo(fresh=True))["id"] != ident


@pytest.mark.skipif(not os.getenv("TRADE_TEST_DATABASE_URL"), reason="PostgreSQL row-lock suite")
def test_concurrent_http_launch_and_step_enqueue_once(env, monkeypatch):
    from app.database import get_db
    from app.demo_center.router import router
    from app.trades import transactions
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    sessions, (owner, _) = env
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(transactions, "actor", lambda db: db.get(User, owner))

    @app.exception_handler(TradeError)
    def error_handler(_, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    with TestClient(app) as client:

        def post(path, payload):
            return client.post(path, json=payload, headers={"Idempotency-Key": uid()})

        with ThreadPoolExecutor(2) as pool:
            launched = list(pool.map(lambda _: post("/api/v1/demo-sessions", {}), range(2)))
        assert [r.status_code for r in launched] == [202, 202]
        assert launched[0].json()["id"] == launched[1].json()["id"]
        ident = launched[0].json()["id"]
        with sessions() as db:
            row = db.get(Launch, ident)
            command = db.get(Command, row.active_command_id)
            command.status = "COMPLETED"
            db.get(Job, command.job_id).status = "SUCCEEDED"
            row.status = "READY"
            db.commit()
        with ThreadPoolExecutor(2) as pool:
            attempted = list(
                pool.map(
                    lambda _: post(
                        f"/api/v1/demo-sessions/{ident}/steps", {"step_code": STEPS[0]["code"]}
                    ),
                    range(2),
                )
            )
        assert sorted(r.status_code for r in attempted) == [202, 409]
        with sessions() as db:
            assert len(list(db.scalars(select(Job).where(Job.stage == "DEMO_STEP")))) == 1
