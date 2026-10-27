"""Integrated demo provisioning, with ordinary durable jobs and encrypted source storage.

No client-supplied identities, trade IDs, commands, provider URLs or facts reach
this runner. Failed partial setups are retained; a new session uses a new namespace.
"""

import time
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from app.compliance import demo as release
from app.compliance.cli import real_storage
from app.compliance.clock import aware, instant
from app.document_desk import jobs as queue
from app.document_desk import register
from app.document_desk import schemas as ds
from app.document_desk.models import Job
from app.freight import demo as freight
from app.freight import runs
from app.freight.models import Run, Template
from app.freight.schemas import RunInput
from app.freight_routes import jobs as routes
from app.freight_routes.models import RouteStudy
from app.freight_routes.schemas import StudyInput
from app.operations import receiving
from app.operations.access import fail
from app.operations.cli import Demo
from app.operations.demo import ROLES, seed_demo
from app.operations.models import Consignment
from app.operations.schemas import ReceiptInput
from app.trades import profiles
from app.trades.models import Trade, uid
from app.trades.schemas import MembershipChange

from . import flows
from .models import Launch
from .service import FRESH_FOR, job_access


class Scenario:
    def __init__(self, sessions, ident, lease):
        self.sessions, self.ident, self.lease = sessions, ident, lease

    def guard(self, db):
        job, _ = queue.leased(db, *self.lease, lock=False)
        row, command = job_access(db, job)
        if row.id != self.ident:
            fail("DEMO_CONTEXT_CHANGED", "Demo command context changed.")
        if command.step_code != "SETUP" and instant(db) >= aware(row.created_at) + FRESH_FOR:
            fail("DEMO_EVIDENCE_EXPIRED", "Start a fresh demo after its evidence window elapses.")
        if row.trade_id and db.get(Trade, row.trade_id).execution_mode != "SIMULATION":
            fail("MODE_MISMATCH", "Integrated demos operate on simulation records only.")
        return row

    def save(self, fx):
        with self.sessions() as db:
            row = self.guard(db)
            row.fixture_json = deepcopy(fx)
            row.trade_id = fx["trade_id"]
            db.commit()

    def job(self, ident):
        from app.document_desk.worker import run_one

        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with self.sessions() as db:
                self.guard(db)
                job = db.get(Job, ident)
                if job.status in {"SUCCEEDED", "PARTIAL"}:
                    return
                if job.status in {"FAILED", "CANCELLED"}:
                    fail(
                        job.last_error_code or "DEMO_CHILD_FAILED",
                        "A demo stage failed; its evidence is preserved.",
                    )
            run_one(self.sessions, ident)
            time.sleep(0.05)
        fail("DEMO_STAGE_TIMEOUT", "Demo stage did not finish; earlier records are preserved.")

    def baseline(self, fx):
        with self.sessions() as db:
            self.guard(db)
            ident = db.get(Run, fx["run_id"]).job_id
        self.job(ident)

    def comparisons(self, fx):
        studies = []
        with self.sessions() as db:
            self.guard(db)
            dataset = db.get(Template, fx["routes"]["direct"]).template_json["dataset_revision_id"]
            owner = db.get(Launch, self.ident).owner_user_id
            from app.trades.models import User
            from app.trades.transactions import Context

            ctx = Context(db.get(User, owner), fx["organizations"]["seller"], uid())
            for weights in [
                dict(
                    distance=7000,
                    duration=1000,
                    road_weather_exposure=0,
                    state_transit_history=2000,
                    toll_exposure=0,
                ),
                dict(
                    distance=1000,
                    duration=7000,
                    road_weather_exposure=0,
                    state_transit_history=2000,
                    toll_exposure=0,
                ),
            ]:
                value = routes.request(
                    db,
                    ctx,
                    fx["consignment_id"],
                    StudyInput(
                        source_mode="RETAINED",
                        departure_at=instant(db) + timedelta(minutes=30),
                        dataset_revision_id=dataset,
                        include_weather=False,
                        weights=weights,
                    ),
                )
                studies.append(value["id"])
            db.commit()
        for ident in studies:
            with self.sessions() as db:
                job_id = db.get(RouteStudy, ident).job_id
            self.job(job_id)
        fx["route_study_ids"] = [*fx.get("route_study_ids", []), *studies]

    def move(self, fx, kind):
        with self.sessions() as db:
            self.guard(db)
            result = flows.move(db, fx, kind)
            db.commit()
            return result["id"]

    def release(self, fx, kind):
        from app.compliance import context, evaluations
        from app.compliance.models import Evaluation
        from app.compliance.schemas_facts import EvaluationInput

        with self.sessions() as db:
            self.guard(db)
            preparer = release.actor(db, fx, "seller-operations")
            version = context.version(db, fx["trade_id"])
            preparer.if_match = f'"{version}"'
            queued = evaluations.request(
                db,
                preparer,
                fx["consignment_id"],
                EvaluationInput(action=kind, expected_context_version=version),
            )
            job_id = db.get(Evaluation, queued["evaluation_id"]).job_id
            db.commit()
        self.job(job_id)
        with self.sessions() as db:
            self.guard(db)
            token = release.authorise(db, fx, fx["consignment_id"], kind, queued["evaluation_id"])
            db.commit()
        fx.setdefault("authorizations", {})[kind] = token["id"]
        self.save(fx)
        return token["id"]

    def receive(self, fx):
        self.move(fx, "ARRIVED")
        harness = Demo(self.sessions, fx)
        with self.sessions() as db:
            self.guard(db)
            from app.operations.quantities import items

            cn = db.get(Consignment, fx["consignment_id"])
            goods = items(db, cn.id)
            receipt = receiving.receive(
                db,
                release.actor(db, fx, "buyer-receiver"),
                cn.id,
                ReceiptInput(
                    client_receipt_id=uid(),
                    received_at=instant(db),
                    lines=[
                        {
                            "consignment_item_id": i.id,
                            "delivered_quantity": str(i.allocated_quantity),
                            "uqc": i.uqc,
                            "observed_condition": "GOOD",
                        }
                        for i in goods
                    ],
                ),
            )
            quantity = str(goods[0].allocated_quantity)
            db.commit()
        with self.sessions() as db:
            self.guard(db)
        harness.inspect(receipt, quantity)
        harness.close({"id": fx["consignment_id"]})
        return receipt["id"]


def install(sessions, ident, lease, store=real_storage):
    runner = Scenario(sessions, ident, lease)
    with sessions() as db:
        row = runner.guard(db)
        if row.fixture_json:
            fail("DEMO_SETUP_ALREADY_STARTED", "Create a fresh demo after interrupted setup.")
        fx = seed_demo(db, namespace="phase4-appdemo-" + ident)
        # Checkpoint before storage calls: the signed import verifies this exact launch.
        row.trade_id, row.fixture_json = fx["trade_id"], deepcopy(fx)
        for role, added in {
            "seller-operations": ["TRADE_PLANNER", "ROUTING_DATA_PREPARER"],
            "seller-approver": [
                "FREIGHT_PROCUREMENT_APPROVER",
                "TRANSPORT_PLAN_APPROVER",
                "ROUTING_DATA_STEWARD",
            ],
            "seller-finance": ["FREIGHT_COST_PREPARER"],
        }.items():
            profiles.change_membership(
                db,
                release.actor(db, fx, "seller-operations"),
                fx["organizations"]["seller"],
                MembershipChange(user_id=fx["users"][role], capabilities=[*ROLES[role][1], *added]),
            )
        profiles.change_membership(
            db,
            release.actor(db, fx, "seller-operations"),
            fx["organizations"]["seller"],
            MembershipChange(user_id=row.owner_user_id, capabilities=["SELLER_DEMO_EXPLORER"]),
        )
        db.commit()
    harness = Demo(sessions, fx, evidence_store=store)
    history = []
    for quantity in ["10", "10", "10", "70"]:
        with sessions() as db:
            runner.guard(db)
        cn = harness.allocate(quantity)
        assignment = harness.assignment(cn, 0)
        current = {**fx, "consignment_id": cn["id"], "original_assignment_id": assignment["id"]}
        with sessions() as db:
            runner.guard(db)
            current["phase4"] = release.prepare(db, fx, cn["id"], store)
            db.commit()
            current.update(freight.prepare(db, fx, cn["id"], modern=True))
            db.commit()
        runner.baseline(current)
        if quantity == "70":
            fx.update(current)
            break
        with sessions() as db:
            runner.guard(db)
            flows.accept(db, current, "A")
            freight.refresh_phase4(db, current, cn["id"], immediate=True)
            # Manifest is obtained from the actual bound context after route acceptance.
            from app.compliance.context import heads

            current["phase4"]["manifest_id"] = heads(
                db, db.get(Consignment, cn["id"])
            ).current_loading_manifest_revision_id
            db.commit()
        for kind in ["PICKUP_CONFIRMED", "DEPARTED"]:
            runner.release(current, kind)
            runner.move(current, kind)
        history.append(cn["id"])
        runner.receive(current)
    fx["history_consignment_ids"] = history
    runner.save(fx)
    runner.comparisons(fx)
    # A distinct, real PDF goes through AUTO extraction. Release uses separately
    # reviewed synthetic documents, never a fabricated OCR confidence value.
    with sessions() as db:
        runner.guard(db)
        ctx = release.actor(db, fx, "seller-operations")
        trade, cn = db.get(Trade, fx["trade_id"]), db.get(Consignment, fx["consignment_id"])
        source = Path(__file__).resolve().parents[4] / "data/fixtures/document-desk/invoice.pdf"
        asset = store(
            db, ctx, trade, cn, "sample-invoice.pdf", source.read_bytes(), "DOCUMENT_FINANCIAL"
        )
        doc = register.create(
            db,
            ctx,
            trade.id,
            ds.Registration(
                document_type="TAX_INVOICE",
                label="SIMULATION extraction sample",
                trade_id=trade.id,
                initial_consignment_id=cn.id,
                primary_attachment_id=asset.id,
                visibility="TRADE_PARTIES",
            ),
        )
        fx["sample_document_version_id"] = doc["current_version_id"]
        job = queue.processing(db, ctx, doc["current_version_id"], ds.Processing(strategy="AUTO"))
        db.commit()
    runner.job(job["job_id"])
    runner.save(fx)
    return {
        "summary": "Documents, freight, routes and three corridor histories are ready.",
        "history_count": len(history),
        "source_mode": "SIMULATION",
        "sample_extraction": "AUTO",
    }


def execute(sessions, ident, code, lease):
    runner = Scenario(sessions, ident, lease)
    with sessions() as db:
        row = runner.guard(db)
        fx = deepcopy(row.fixture_json)
    result = {}
    if code == "CORRIDOR_CHANGE":
        with sessions() as db:
            runner.guard(db)
            result["event_revision_id"] = flows.restriction(db, fx)
            planner = release.actor(db, fx, "seller-operations")
            from app.compliance import context

            version = context.version(db, fx["trade_id"])
            planner.if_match = f'"{version}"'
            request = RunInput.model_validate(
                {**fx["run_request"], "expected_context_version": version}
            )
            run = runs.request(db, planner, fx["consignment_id"], request)
            fx["run_id"] = run["run_id"]
            db.commit()
        runner.baseline(fx)
        runner.comparisons(fx)
        result["summary"] = (
            "Direct road excluded; alternatives recalculated. Fixed offers unchanged."
        )
    elif code == "ACCEPT_FREIGHT":
        with sessions() as db:
            runner.guard(db)
            accepted = flows.accept(db, fx, "B")
            freight.refresh_phase4(db, fx, fx["consignment_id"], immediate=True)
            from app.compliance.context import heads

            fx["phase4"]["manifest_id"] = heads(
                db, db.get(Consignment, fx["consignment_id"])
            ).current_loading_manifest_revision_id
            db.commit()
            result = {
                "summary": "Alternate accepted by payer and carrier. Fresh release required.",
                "commitment_id": accepted["commitment_id"],
            }
    elif code in {"PICKUP_RELEASE", "DEPARTURE_RELEASE"}:
        kind = "PICKUP_CONFIRMED" if code == "PICKUP_RELEASE" else "DEPARTED"
        result = {
            "summary": "Evaluation, independent review, packet and driver acknowledgment complete.",
            "authorization_id": runner.release(fx, kind),
        }
    elif code in {"PICKUP", "DEPART"}:
        result = {
            "summary": "Movement recorded and its action-specific authorization consumed.",
            "movement_event_id": runner.move(
                fx, "PICKUP_CONFIRMED" if code == "PICKUP" else "DEPARTED"
            ),
        }
    elif code == "RECEIVE":
        result = {
            "summary": "Goods received, inspected and delivery closed.",
            "receipt_id": runner.receive(fx),
        }
    elif code == "PAYMENT":
        with sessions() as db:
            runner.guard(db)
        harness = Demo(sessions, fx)
        harness.payment(harness.schedule())
        result = {
            "summary": "Declared payment acknowledged and allocated. Bank settlement not verified."
        }
    else:
        fail("DEMO_STEP_UNKNOWN", "Unregistered simulation step.")
    runner.save(fx)
    return result
