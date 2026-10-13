import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import (  # noqa: E402
    demo,
    handoff,
    suites,
    templates,
    turnover,
)
from app.compliance.clock import aware, use_test_clock  # noqa: E402
from app.compliance.models import Authorization  # noqa: E402
from app.operations import movement  # noqa: E402
from app.operations.cli import Demo  # noqa: E402
from app.operations.demo import seed_demo  # noqa: E402
from app.operations.schemas import ShipmentEventInput  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import now, uid  # noqa: E402
from app.trades.router import router  # noqa: E402,F401


@pytest.fixture()
def fixture(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gate.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        fx = seed_demo(db, namespace="phase4-test")
    harness = Demo(sessions, fx)
    cn = harness.allocate("100")
    assignment = harness.assignment(cn, 0)
    with sessions() as db:
        prepared = demo.prepare(db, fx, cn["id"])
        db.commit()
    yield sessions, fx, cn, assignment, prepared
    engine.dispose()


def test_registered_pack_cannot_skip_required_evidence():
    pack = templates.candidate([uid()]).model_dump(mode="json", by_alias=True)
    assert suites.run(pack)["passed"]
    pack["rules"][0]["satisfaction_expression"] = {"op": "literal", "value": True}
    assert not suites.run(pack)["passed"]


def test_turnover_history_and_hsn_are_independent():
    declaration = {
        "assessment_invoice_date": "2026-04-01",
        "relevant_financial_years": [
            {
                "financial_year_start": 2024,
                "existence_status": "IN_EXISTENCE",
                "pan_aggregate_turnover_minor": "6000000000",
            },
            {
                "financial_year_start": 2025,
                "existence_status": "IN_EXISTENCE",
                "pan_aggregate_turnover_minor": "4000000000",
            },
        ],
        "history_completeness_declared": False,
        "supplier_exclusion_code": "NONE_CLAIMED",
    }
    value = turnover.derive(declaration)
    assert value["exceeds_five_crore"] is True
    assert value["hsn_required_digits"] == 4
    declaration["relevant_financial_years"][0]["pan_aggregate_turnover_minor"] = "5000000000"
    assert turnover.derive(declaration)["exceeds_five_crore"] is None


def test_full_independent_gate_and_atomic_consumption(fixture):
    sessions, fx, cn, assignment, prepared = fixture
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
            "items": [
                {
                    "consignment_item_id": i["id"],
                    "loaded_quantity": i["allocated_quantity"],
                    "uqc": i["uqc"],
                }
                for i in cn["items"]
            ],
            "actual_gross_weight_kg": "400",
            "actual_package_count": 4,
        },
    }
    with sessions() as db:
        state = handoff.readiness(
            db, demo.actor(db, fx, "driver-one"), cn["id"], "PICKUP_CONFIRMED"
        )
        assert state["state"] == "READY", state
        event = movement.event(
            db, demo.actor(db, fx, "driver-one"), cn["id"], ShipmentEventInput.model_validate(body)
        )
        db.commit()
        assert db.get(Authorization, token["id"]).consumed_event_id == event["id"]
    with sessions() as db:
        replay = movement.event(
            db, demo.actor(db, fx, "driver-one"), cn["id"], ShipmentEventInput.model_validate(body)
        )
        assert replay["id"] == event["id"]
        db.commit()
    with sessions() as db:
        next_token = demo.authorise(db, fx, cn["id"], "DEPARTED")
        db.commit()
        assert next_token["id"] != token["id"]


def test_gate_requires_authorisation_and_failed_payload_does_not_consume(fixture):
    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        db.commit()
    body = {
        "client_event_id": uid(),
        "event_type": "PICKUP_CONFIRMED",
        "assignment_id": assignment["id"],
        "occurred_at": now(),
        "loading_manifest_revision_id": prepared["manifest_id"],
        "payload": {
            "items": [
                {
                    "consignment_item_id": i["id"],
                    "loaded_quantity": i["allocated_quantity"],
                    "uqc": i["uqc"],
                }
                for i in cn["items"]
            ],
            "actual_gross_weight_kg": "401",
            "actual_package_count": 4,
        },
    }
    for supplied, code in [
        (None, "COMPLIANCE_NOT_READY"),
        (token["id"], "LOADING_MANIFEST_MISMATCH"),
    ]:
        with sessions() as db:
            body["dispatch_authorization_id"] = supplied
            with pytest.raises(TradeError) as error:
                movement.event(
                    db,
                    demo.actor(db, fx, "driver-one"),
                    cn["id"],
                    ShipmentEventInput.model_validate(body),
                )
            assert error.value.code == code
            db.rollback()
            assert db.get(Authorization, token["id"]).consumed_event_id is None


def test_temporal_expiry_and_backdated_event(fixture):
    sessions, fx, cn, assignment, prepared = fixture
    with sessions() as db:
        token = demo.authorise(db, fx, cn["id"], "PICKUP_CONFIRMED")
        expiry = db.get(Authorization, token["id"]).expires_at
        db.commit()
    with use_test_clock(lambda: aware(expiry) + timedelta(seconds=1)):
        with sessions() as db:
            state = handoff.readiness(
                db, demo.actor(db, fx, "driver-one"), cn["id"], "PICKUP_CONFIRMED"
            )
            assert state["state"] != "READY"
