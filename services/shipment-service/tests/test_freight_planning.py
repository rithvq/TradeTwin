import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import demo as release_demo  # noqa: E402
from app.compliance.clock import aware, use_test_clock  # noqa: E402
from app.document_desk.worker import run_one  # noqa: E402
from app.freight import assessment, calculator, commitments, demo, runs, views  # noqa: E402
from app.freight.models import Candidate, Quote, Run  # noqa: E402
from app.freight.schemas import CarrierDecision, SelectionDecision, SelectionInput  # noqa: E402
from app.operations.models import Booking, Consignment, Event, PaymentAllocation  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402


@pytest.fixture()
def fx(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'freight.db'}")
    schema = f"freight_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        if not url:
            connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine)
    sessions = sessionmaker(engine)
    data = demo.seed(sessions, "phase4-freight-test")
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


def test_baseline_worker_cost_constraints_and_pareto(fx):
    sessions, data = fx
    with sessions() as db:
        run = db.get(Run, data["run_id"])
        assert run.job_state == "COMPLETED"
        result = run.result_json
        candidates = {
            next(k for k, v in data["quotes"].items() if v == c["quote_revision_id"]): c
            for c in result["candidates"]
        }
        assert candidates["A"]["scenarios"]["BASE"]["cost"]["comparison_total_minor"] == "1890000"
        assert candidates["B"]["scenarios"]["BASE"]["cost"]["comparison_total_minor"] == "2205000"
        assert candidates["C"]["scenarios"]["BASE"]["planning_outcome"] == "NEEDS_INPUT"
        assert candidates["D"]["scenarios"]["BASE"]["cost"]["comparison_total_minor"] is None
        cheapest = result["rankings"]["BASE"]["LOWEST_COMPARABLE_COST"]
        fastest = result["rankings"]["BASE"]["EARLIEST_ESTIMATED_ARRIVAL"]
        assert cheapest[0]["candidate_id"] == candidates["A"]["candidate_id"], candidates["A"]
        assert fastest[0]["candidate_id"] == candidates["B"]["candidate_id"]
        assert all(r["pareto_member"] for r in cheapest)
        waited = candidates["A"]["scenarios"]["EXTRA_WAIT"]
        assert waited["cost"]["scenario_contingent_charge_minor"] == "50000"
        assert waited["cost"]["comparison_total_minor"] == "1940000"
        assert db.scalar(select(func.count()).select_from(Booking)) == 2
        assert db.scalar(select(func.count()).select_from(Event)) == 0


def proposal(db, data):
    cn = db.get(Consignment, data["consignment_id"])
    run = db.get(Run, data["run_id"])
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.run_id == run.id, Candidate.quote_revision_id == data["quotes"]["A"]
        )
    )
    quote = db.get(Quote, candidate.quote_revision_id)
    ctx = release_demo.actor(db, data, "seller-operations")
    ctx.if_match = f'"{cn.row_version}"'
    value = commitments.propose(
        db,
        ctx,
        cn.id,
        SelectionInput(
            run_id=run.id,
            candidate_id=candidate.id,
            candidate_hash=candidate.content_hash,
            quote_revision_id=quote.id,
            quote_hash=quote.content_hash,
            scenario_code="BASE",
            expected_existing_assignment_id=cn.active_assignment_id,
            expected_consignment_row_version=cn.row_version,
            expected_context_version=run.input_json["context"]["compliance_context_version"],
        ),
    )
    return value


def approve(db, data, value):
    ctx = release_demo.actor(db, data, "seller-approver")
    ctx.if_match = value["etag"]
    return commitments.approve(
        db,
        ctx,
        value["id"],
        SelectionDecision(
            proposal_hash=value["proposal_hash"],
            quote_hash=value["quote_hash"],
            decision="APPROVE",
            acknowledged_limitation_codes=[
                "ESTIMATE_NOT_GUARANTEE",
                "AVAILABILITY_NOT_RESERVATION",
                "FRESH_PHASE4_RELEASE_REQUIRED",
            ],
            reason="Exact fixed offer approved",
        ),
        "PAYER",
    )


def test_atomic_same_resource_replacement_and_fresh_release(fx):
    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approval = approve(db, data, value)
        assert db.scalar(select(func.count()).select_from(Booking)) == 2
        ctx = release_demo.actor(db, data, "carrier-dispatcher")
        ctx.if_match = approval["etag"]
        accepted = commitments.accept(
            db,
            ctx,
            value["id"],
            CarrierDecision(
                proposal_hash=value["proposal_hash"],
                quote_hash=value["quote_hash"],
                proposed_assignment_id=approval["proposed_assignment_id"],
                decision="ACCEPT",
                reason="Exact resources and offer accepted",
            ),
        )
        assert accepted["dispatch_authorisation"] is None
        assert (
            accepted["new_context_version"]
            == db.get(Run, data["run_id"]).input_json["context"]["compliance_context_version"] + 1
        )
        assert (
            db.scalar(
                select(func.count()).select_from(Booking).where(Booking.released_at.is_(None))
            )
            == 2
        )
        assert db.scalar(select(func.count()).select_from(Event)) == 0
        assert db.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
        own = views.commitment_view(db, ctx, accepted["commitment_id"])["commitment"]
        assert "price_snapshot" in own
        assert "comparison_cost_snapshot" not in own
        driver = release_demo.actor(db, data, "driver-one")
        limited = views.commitment_view(db, driver, accepted["commitment_id"])["commitment"]
        assert "price_snapshot" not in limited and "service_snapshot" not in limited
        assert (
            views.route_plan(db, driver, data["consignment_id"])["accepted_assignment_id"]
            == accepted["accepted_assignment_id"]
        )
        db.commit()


def test_privacy_masks_price_and_rankings(fx):
    sessions, data = fx
    with sessions() as db:
        operator = release_demo.actor(db, data, "seller-operations")
        response = views.run_view(db, operator, data["run_id"])
        assert "rankings" not in response
        assert all("cost" not in s for c in response["candidates"] for s in c["scenarios"].values())
        with pytest.raises(TradeError):
            views.run_view(db, release_demo.actor(db, data, "carrier-dispatcher"), data["run_id"])
        with pytest.raises(TradeError):
            views.run_view(db, release_demo.actor(db, data, "driver-one"), data["run_id"])


@pytest.mark.parametrize(
    "wait,expected", [(0, 0), (30, 0), (31, 25000), (45, 25000), (46, 50000), (5000, 200000)]
)
def test_wait_boundaries(wait, expected):
    assert (
        calculator.contingent(
            {
                "free_minutes": 30,
                "billing_increment_minutes": 15,
                "charge_per_increment_gross_minor": "25000",
                "maximum_charge_gross_minor": "200000",
            },
            wait,
        )
        == expected
    )


def test_quote_expiry_at_boundary(fx):
    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approval = approve(db, data, value)
        quote = db.get(Quote, data["quotes"]["A"])
        with use_test_clock(lambda: aware(quote.accept_by)):
            ctx = release_demo.actor(db, data, "carrier-dispatcher")
            ctx.if_match = approval["etag"]
            with pytest.raises(TradeError, match="deadline"):
                commitments.accept(
                    db,
                    ctx,
                    value["id"],
                    CarrierDecision(
                        proposal_hash=value["proposal_hash"],
                        quote_hash=value["quote_hash"],
                        proposed_assignment_id=approval["proposed_assignment_id"],
                        decision="ACCEPT",
                        reason="Expired offer",
                    ),
                )


@pytest.mark.parametrize(
    "path,value,expected",
    [
        ("overall_height_mm", None, "NEEDS_INPUT"),
        ("overall_width_mm", None, "NEEDS_INPUT"),
        ("overall_length_mm", None, "NEEDS_INPUT"),
        ("combined_tare_weight_kg", None, "NEEDS_INPUT"),
        ("maximum_actual_axle_load_kg", None, "NEEDS_INPUT"),
        ("maximum_authorised_combined_weight_kg", "4399.999999", "BLOCKED"),
        ("maximum_authorised_combined_weight_kg", "4400", "SUPPORTED_PLAN"),
    ],
)
def test_exact_vehicle_requirements(fx, path, value, expected):
    from copy import deepcopy

    sessions, data = fx
    with sessions() as db:
        snapshot = deepcopy(db.get(Run, data["run_id"]).input_json)
        source = snapshot["sources"][0]
        source["profile"][path] = value
        assert (
            assessment.assess(snapshot, source, runs.BASE, "stable-candidate")["planning_outcome"]
            == expected
        )


@pytest.mark.parametrize(
    "capacity,expected", [("400", "SUPPORTED_PLAN"), ("399.999999", "BLOCKED")]
)
def test_capacity_boundary_has_no_float_tolerance(fx, capacity, expected):
    from copy import deepcopy

    sessions, data = fx
    with sessions() as db:
        snapshot = deepcopy(db.get(Run, data["run_id"]).input_json)
        source = snapshot["sources"][0]
        source["profile"]["vehicle_declarations"]["declared_payload_capacity_kg"] = capacity
        assert (
            assessment.assess(snapshot, source, runs.BASE, "stable-candidate")["planning_outcome"]
            == expected
        )


def test_published_history_is_immutable_at_database_boundary(fx):
    from app.freight.models import RFQ
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    sessions, data = fx
    targets = [
        (Quote, data["quotes"]["A"], "quote_json"),
        (Run, data["run_id"], "input_json"),
        (RFQ, data["rfq_id"], "request_json"),
    ]
    for model, ident, column in targets:
        with sessions() as db:
            with pytest.raises(DBAPIError):
                db.execute(
                    update(model).where(model.id == ident).values({column: {"tampered": True}})
                )


def test_generic_assignment_acceptance_cannot_bypass_freight(fx):
    from app.operations import transport
    from app.operations.schemas import AssignmentDecision

    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approved = approve(db, data, value)
        quote = db.get(Quote, data["quotes"]["A"])
        with pytest.raises(TradeError) as error:
            transport.decide(
                db,
                release_demo.actor(db, data, "carrier-dispatcher"),
                approved["proposed_assignment_id"],
                AssignmentDecision(
                    decision="ACCEPT",
                    vehicle_id=quote.vehicle_id,
                    driver_user_id=quote.driver_user_id,
                    reason="Attempt weaker endpoint",
                ),
            )
        assert error.value.code == "FREIGHT_COMMITMENT_ACCEPTANCE_REQUIRED"


def test_bilateral_cancellation_preserves_goods_ledger(fx):
    from app.freight.models import Commitment, PlanHead
    from app.freight.schemas import CancellationDecisionInput, CancellationInput

    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approved = approve(db, data, value)
        carrier = release_demo.actor(db, data, "carrier-dispatcher")
        carrier.if_match = approved["etag"]
        accepted = commitments.accept(
            db,
            carrier,
            value["id"],
            CarrierDecision(
                proposal_hash=value["proposal_hash"],
                quote_hash=value["quote_hash"],
                proposed_assignment_id=approved["proposed_assignment_id"],
                decision="ACCEPT",
                reason="Carrier accepts",
            ),
        )
        payer = release_demo.actor(db, data, "seller-approver")
        commitment = db.get(Commitment, accepted["commitment_id"])
        cancellation = commitments.propose_cancellation(
            db,
            payer,
            commitment.id,
            CancellationInput(
                commitment_hash=commitment.content_hash,
                reason="Agreed synthetic cancellation",
                proposed_fee_position="NO_FEE",
                proposed_fee_minor="0",
                proposed_fee_note="No payment/refund implied",
            ),
        )
        payer.if_match = cancellation["etag"]
        vote = commitments.cancel_commitment(
            db,
            payer,
            cancellation["id"],
            CancellationDecisionInput(
                proposal_hash=cancellation["proposal_hash"],
                decision_role="PAYER",
                decision="APPROVE",
                reason="Payer agrees",
            ),
        )
        carrier.if_match = vote["etag"]
        final = commitments.cancel_commitment(
            db,
            carrier,
            cancellation["id"],
            CancellationDecisionInput(
                proposal_hash=cancellation["proposal_hash"],
                decision_role="CARRIER",
                decision="APPROVE",
                reason="Carrier agrees",
            ),
        )
        assert final["status"] == "AGREED"
        assert (
            db.scalar(
                select(func.count()).select_from(Booking).where(Booking.released_at.is_(None))
            )
            == 0
        )
        assert (
            db.scalar(
                select(PlanHead.current_revision_id).where(
                    PlanHead.consignment_id == data["consignment_id"]
                )
            )
            is None
        )
        assert db.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
        assert db.get(Commitment, commitment.id).content_hash == commitment.content_hash
        db.commit()


def test_fresh_phase4_handoff_cannot_reuse_old_release(fx):
    from app.compliance import handoff

    sessions, data = fx
    with sessions() as db:
        old = release_demo.authorise(db, data, data["consignment_id"], "PICKUP_CONFIRMED")
        value = proposal(db, data)
        approved = approve(db, data, value)
        carrier = release_demo.actor(db, data, "carrier-dispatcher")
        carrier.if_match = approved["etag"]
        commitments.accept(
            db,
            carrier,
            value["id"],
            CarrierDecision(
                proposal_hash=value["proposal_hash"],
                quote_hash=value["quote_hash"],
                proposed_assignment_id=approved["proposed_assignment_id"],
                decision="ACCEPT",
                reason="Commit handoff",
            ),
        )
        readiness = handoff.readiness(
            db,
            release_demo.actor(db, data, "driver-one"),
            data["consignment_id"],
            "PICKUP_CONFIRMED",
        )
        assert readiness["state"] != "READY", old
        demo.refresh_phase4(db, data, data["consignment_id"])
        new = release_demo.authorise(db, data, data["consignment_id"], "PICKUP_CONFIRMED")
        assert new["id"] != old["id"]
        assert (
            handoff.readiness(
                db,
                release_demo.actor(db, data, "driver-one"),
                data["consignment_id"],
                "PICKUP_CONFIRMED",
            )["state"]
            == "READY"
        )
        assert db.scalar(select(func.count()).select_from(Event)) == 0
        from app.freight import routing
        from app.freight.models import Dataset, Template
        from app.freight.schemas import HashCommand

        quote = db.get(Quote, data["quotes"]["A"])
        dataset = db.get(
            Dataset, db.get(Template, quote.route_template_revision_id).dataset_revision_id
        )
        routing.dataset_event(
            db,
            release_demo.actor(db, data, "seller-approver"),
            dataset.id,
            HashCommand(content_hash=dataset.content_hash, reason="Suspend source after release"),
            "SUSPENDED",
        )
        db.flush()
        assert (
            handoff.readiness(
                db,
                release_demo.actor(db, data, "driver-one"),
                data["consignment_id"],
                "PICKUP_CONFIRMED",
            )["state"]
            != "READY"
        )
        db.commit()


def test_unassigned_planning_evidence_and_driver_privacy(fx):
    from app.compliance import facts
    from app.compliance.models import TransportEvidence
    from app.compliance.schemas_facts import TransportInput
    from app.freight.models import Invitation
    from app.operations.models import Vehicle
    from app.trades.models import uid

    sessions, data = fx
    with sessions() as db:
        quote = db.get(Quote, data["quotes"]["A"])
        old = db.get(Vehicle, quote.vehicle_id)
        vehicle = Vehicle(
            id=uid(),
            carrier_organization_id=old.carrier_organization_id,
            registration_number="KA01PLAN5678",
            vehicle_json=old.vehicle_json,
            execution_mode="SIMULATION",
            created_by=old.created_by,
        )
        db.add(vehicle)
        db.flush()
        payload = TransportInput(
            subject_type="VEHICLE",
            subject_id=vehicle.id,
            evidence_type="GOODS_PERMIT",
            source_mode="SELF_DECLARATION",
            limitations=["Planning only; self declaration does not prove permit coverage"],
        )
        carrier = release_demo.actor(db, data, "carrier-dispatcher")
        created = facts.transport(db, carrier, data["consignment_id"], payload)
        assert db.get(TransportEvidence, created["id"]).assignment_id is None
        assert db.scalar(select(func.count()).select_from(Booking)) == 2
        with pytest.raises(TradeError):
            facts.transport(
                db, release_demo.actor(db, data, "driver-one"), data["consignment_id"], payload
            )
        invitation = db.scalar(select(Invitation).where(Invitation.rfq_id == data["rfq_id"]))
        invitation.revoked_at = aware(db.get(Run, data["run_id"]).evaluated_as_of)
        db.flush()
        with pytest.raises(TradeError):
            facts.transport(db, carrier, data["consignment_id"], payload)


def test_retained_generation_uses_durable_worker(fx):
    from app.freight import routing
    from app.freight.models import Generation, Template
    from app.freight.schemas import GenerateInput

    sessions, data = fx
    with sessions() as db:
        run = db.get(Run, data["run_id"])
        quote = db.get(Quote, data["quotes"]["A"])
        template = db.get(Template, quote.route_template_revision_id)
        result = routing.generate(
            db,
            release_demo.actor(db, data, "seller-operations"),
            data["consignment_id"],
            GenerateInput(
                pickup_location_revision_id=run.input_json["context"][
                    "pickup_location_revision_id"
                ],
                drop_location_revision_id=run.input_json["context"]["drop_location_revision_id"],
                vehicle_profile_revision_id=quote.profile_revision_id,
                departure_at=run.input_json["planning_intent"]["intended_departure_at"],
                dataset_revision_id_or_provider_connection_id=template.dataset_revision_id,
            ),
        )
        job = db.get(Generation, result["job_id"])
        assert job.job_state == "QUEUED"
        worker_job_id = job.job_id
        db.commit()
    assert run_one(sessions, worker_job_id)
    with sessions() as db:
        job = db.get(Generation, result["job_id"])
        assert job.job_state == "COMPLETED"
        assert job.result_json["templates"]


def test_graph_replay_keeps_price_masking(fx):
    sessions, data = fx
    with sessions() as db:
        graph = views.graph(db, release_demo.actor(db, data, "seller-operations"), data["run_id"])
        types = {n["type"] for n in graph["nodes"]}
        assert {
            "RFQ",
            "Quote",
            "Route",
            "RouteDataset",
            "VehicleProfile",
            "PlanningConstraint",
        } <= types
        assert "CostAssumptions" not in types
        with pytest.raises(TradeError):
            views.graph(db, release_demo.actor(db, data, "driver-one"), data["run_id"])


def test_current_rfq_heads_expose_owned_quotes_and_acceptance_requests(fx):
    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approve(db, data, value)
        response = views.rfq_view(
            db, release_demo.actor(db, data, "carrier-dispatcher"), data["rfq_id"]
        )
        assert len(response["quotes"]) == 4
        assert response["selection_requests"] == [
            {"id": value["id"], "lifecycle": "PENDING_CARRIER_ACCEPTANCE"}
        ]


@pytest.mark.skipif(not os.getenv("TRADE_TEST_DATABASE_URL"), reason="PostgreSQL race test")
def test_quote_withdrawal_and_acceptance_serialize(fx):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.freight import offers
    from app.freight.models import Commitment, QuoteHead
    from app.freight.schemas import HashCommand

    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approved = approve(db, data, value)
        quote = db.get(Quote, data["quotes"]["A"])
        quote_etag = f'"{db.get(QuoteHead, quote.quote_head_id).row_version}"'
        db.commit()
    barrier = Barrier(2)

    def operation(withdraw):
        with sessions() as db:
            ctx = release_demo.actor(db, data, "carrier-dispatcher")
            ctx.if_match = quote_etag if withdraw else approved["etag"]
            barrier.wait(timeout=15)
            try:
                if withdraw:
                    offers.quote_event(
                        db,
                        ctx,
                        data["quotes"]["A"],
                        HashCommand(
                            content_hash=value["quote_hash"], reason="Concurrent withdrawal"
                        ),
                        "WITHDRAWN",
                    )
                else:
                    commitments.accept(
                        db,
                        ctx,
                        value["id"],
                        CarrierDecision(
                            proposal_hash=value["proposal_hash"],
                            quote_hash=value["quote_hash"],
                            proposed_assignment_id=approved["proposed_assignment_id"],
                            decision="ACCEPT",
                            reason="Concurrent exact acceptance",
                        ),
                    )
                db.commit()
                return True
            except TradeError:
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(operation, side) for side in [True, False]]
        results = [f.result(timeout=60) for f in futures]
    assert sum(results) == 1
    with sessions() as db:
        quote = db.get(Quote, data["quotes"]["A"])
        head = db.get(QuoteHead, quote.quote_head_id)
        count = db.scalar(select(func.count()).select_from(Commitment))
        assert (head.lifecycle_projection, count) in {("ACCEPTED", 1), ("WITHDRAWN", 0)}
        assert (
            db.scalar(
                select(func.count()).select_from(Booking).where(Booking.released_at.is_(None))
            )
            == 2
        )


def test_exact_cost_rounding_and_directional_scenario(fx):
    from copy import deepcopy
    from uuid import uuid4

    from app.freight.routing import path_snapshot

    sessions, data = fx
    with sessions() as db:
        snapshot = deepcopy(db.get(Run, data["run_id"]).input_json)
    source = snapshot["sources"][0]
    source["quote"]["service_coverage"] = [
        {"category_code": "TOLL", "coverage": "EXCLUDED_PAYER_COST", "explanation": "External toll"}
    ]
    snapshot["comparison_policy"] = "ALLOW_DECLARED_ESTIMATES"
    snapshot["cost_assumptions"] = {
        "external_cost_components": [
            {
                "component_id": str(uuid4()),
                "category": "TOLL",
                "label": "Exact metre-based toll estimate",
                "applies_to_quote_revision_ids": [source["quote_revision_id"]],
                "basis": "PER_KM",
                "rate_minor_per_unit": "0.001389",
                "quantity_source": "ROUTE_DISTANCE_KM",
                "amount_includes_applicable_tax": True,
                "source_kind": "USER_ESTIMATE",
                "valid_until": None,
            }
        ],
        "recipient_tax_cash_estimates": [],
    }
    base = assessment.assess(snapshot, source, runs.BASE, "exact")
    # 360 km * .001389 paise = .50004 paise -> one paise, once.
    assert base["cost"]["external_cost_minor"] == "1"
    stress = {
        **runs.BASE,
        "scenario_code": "EXTRA_WAIT",
        "delay_placement": "DESTINATION_UNLOADING",
        "additional_wait_minutes": 46,
    }
    destination = assessment.assess(snapshot, source, stress, "exact")
    assert destination["estimated_arrival_at"] == base["estimated_arrival_at"]
    assert destination["estimated_completion_at"] != base["estimated_completion_at"]
    # A state revisited on a later edge is not deduplicated globally.
    graph = source["dataset"]
    graph["edges"][0]["ordered_state_sequence"] = ["29", "33", "29"]
    graph["edges"][1]["ordered_state_sequence"] = ["29", "33"]
    route = path_snapshot(
        graph, source["template"], source["profile"], snapshot["context"]["cargo_snapshot"]
    )
    assert route["state_sequence"] == ["29", "33", "29", "33"]


@pytest.mark.skipif(not os.getenv("TRADE_TEST_DATABASE_URL"), reason="PostgreSQL race test")
def test_duplicate_acceptance_replays_one_atomic_commitment(fx):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.freight.models import Commitment
    from app.freight.router import authorize
    from app.trades.transactions import mutate
    from starlette.requests import Request
    from tradetwin_security import identity

    sessions, data = fx
    with sessions() as db:
        value = proposal(db, data)
        approved = approve(db, data, value)
        initial_context = db.get(Run, data["run_id"]).input_json["context"][
            "compliance_context_version"
        ]
        db.commit()
    payload = CarrierDecision(
        proposal_hash=value["proposal_hash"],
        quote_hash=value["quote_hash"],
        proposed_assignment_id=approved["proposed_assignment_id"],
        decision="ACCEPT",
        reason="Idempotent carrier acceptance",
    )
    barrier = Barrier(2)

    def accept_once():
        principal = identity.set({"id": data["subjects"]["carrier-dispatcher"]})
        try:
            with sessions() as db:
                request = Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "scheme": "http",
                        "server": ("test", 80),
                        "path": f"/api/v1/tradetwin-selections/{value['id']}/carrier-decisions",
                        "query_string": b"",
                        "headers": [
                            (b"x-organization-id", data["organizations"]["carrier"].encode()),
                            (b"idempotency-key", b"same-carrier-acceptance"),
                            (b"if-match", approved["etag"].encode()),
                        ],
                    }
                )
                barrier.wait(timeout=15)
                result = mutate(
                    request,
                    db,
                    lambda session, ctx, command: commitments.accept(
                        session, ctx, value["id"], command
                    ),
                    payload,
                    authorize=lambda session, ctx: authorize(
                        session, ctx, value["id"], "selection", "CARRIER", payload
                    ),
                )
                return json.loads(result.body)
        finally:
            identity.reset(principal)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(accept_once) for _ in range(2)]
        results = [f.result(timeout=60) for f in futures]
    assert results[0] == results[1]
    assert results[0]["new_context_version"] == initial_context + 1
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Commitment)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(Booking).where(Booking.released_at.is_(None))
            )
            == 2
        )


@pytest.mark.skipif(not os.getenv("TRADE_TEST_DATABASE_URL"), reason="PostgreSQL race test")
def test_pickup_and_incompatible_commitment_cannot_both_succeed(fx):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.compliance.clock import instant
    from app.compliance.models import Heads
    from app.freight.models import Commitment
    from app.operations import movement
    from app.operations.quantities import items
    from app.operations.schemas import ShipmentEventInput

    sessions, data = fx
    with sessions() as db:
        release = release_demo.authorise(db, data, data["consignment_id"], "PICKUP_CONFIRMED")
        manifest = db.get(Heads, data["consignment_id"]).current_loading_manifest_revision_id
        value = proposal(db, data)
        approved = approve(db, data, value)
        loaded = [
            {
                "consignment_item_id": i.id,
                "loaded_quantity": str(i.allocated_quantity),
                "uqc": i.uqc,
            }
            for i in items(db, data["consignment_id"])
        ]
        db.commit()
    barrier = Barrier(2)

    def operate(pickup):
        with sessions() as db:
            ctx = release_demo.actor(db, data, "driver-one" if pickup else "carrier-dispatcher")
            ctx.if_match = approved["etag"]
            barrier.wait(timeout=15)
            try:
                if pickup:
                    movement.event(
                        db,
                        ctx,
                        data["consignment_id"],
                        ShipmentEventInput.model_validate(
                            {
                                "client_event_id": str(uuid4()),
                                "event_type": "PICKUP_CONFIRMED",
                                "occurred_at": instant(db),
                                "assignment_id": data["original_assignment_id"],
                                "dispatch_authorization_id": release["id"],
                                "loading_manifest_revision_id": manifest,
                                "payload": {
                                    "actual_gross_weight_kg": "400",
                                    "actual_package_count": 100,
                                    "items": loaded,
                                },
                            }
                        ),
                    )
                else:
                    commitments.accept(
                        db,
                        ctx,
                        value["id"],
                        CarrierDecision(
                            proposal_hash=value["proposal_hash"],
                            quote_hash=value["quote_hash"],
                            proposed_assignment_id=approved["proposed_assignment_id"],
                            decision="ACCEPT",
                            reason="Competing pre-pickup replacement",
                        ),
                    )
                db.commit()
                return True
            except TradeError:
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(operate, pickup) for pickup in [True, False]]
        results = [f.result(timeout=60) for f in futures]
    assert sum(results) == 1
    with sessions() as db:
        count = db.scalar(select(func.count()).select_from(Commitment))
        events = db.scalar(select(func.count()).select_from(Event))
        assert (count, events) in {(1, 0), (0, 1)}
