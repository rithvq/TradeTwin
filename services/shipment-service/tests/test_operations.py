import os
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from tradetwin_security import identity

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import context, demo  # noqa: E402
from app.database import get_db  # noqa: E402
from app.operations.cli import Demo  # noqa: E402
from app.operations.demo import ROLES, seed_demo  # noqa: E402
from app.operations.models import Inspection, Schedule  # noqa: E402
from app.operations.schedules import amounts  # noqa: E402
from app.trades.errors import install_handlers  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Audit, Grant, Membership, Trade, now  # noqa: E402
from app.trades.router import router  # noqa: E402
from app.trades.schemas import GoodsLine  # noqa: E402


@pytest.fixture()
def flow(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(
        url or f"sqlite:///{tmp_path / 'operations.db'}",
        connect_args={} if url else {"check_same_thread": False},
    )
    schema = f"operations_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    migrate(engine)
    migrate(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        fixtures = seed_demo(db)
    app = FastAPI()
    app.include_router(router)
    install_handlers(app)

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency

    @app.middleware("http")
    async def test_identity(request, call_next):
        name = request.headers.get("X-Test-User")
        token = identity.set({"id": fixtures["subjects"][name]} if name else None)
        try:
            return await call_next(request)
        finally:
            identity.reset(token)

    with TestClient(app) as client:
        yield Flow(client, fixtures, sessions, bool(url))
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


class Flow:
    def __init__(self, client, fixtures, sessions, postgres):
        self.client, self.fx, self.sessions, self.postgres = client, fixtures, sessions, postgres
        self.trade_id = fixtures["trade_id"]

    def call(
        self,
        path,
        payload=None,
        user="seller-operations",
        etag=None,
        key=None,
        method=None,
        expected=200,
    ):
        headers = {
            "X-Test-User": user,
            "X-Organization-Id": self.fx["organizations"][ROLES[user][0]],
            "Idempotency-Key": key or str(uuid4()),
        }
        if etag:
            headers["If-Match"] = etag
        response = self.client.request(
            method or ("POST" if payload is not None else "GET"),
            "/api/v1" + path,
            json=payload,
            headers=headers,
        )
        if expected is not None:
            assert response.status_code == expected, response.text
        return response.json() if expected is not None else response

    def trade(self):
        return self.call(f"/trades/{self.trade_id}")

    def workspace(self, user="seller-operations"):
        return self.call(f"/trades/{self.trade_id}/operations", user=user)

    def cn(self, ident, user="seller-operations"):
        return self.call(f"/consignments/{ident}", user=user)

    def plan(self, quantity="40", **changes):
        accepted = self.trade()["accepted_revision"]
        delivery = accepted["facts"]["delivery_requirements"]
        body = {
            "source_accepted_revision_id": accepted["id"],
            "coordinating_organization_id": self.fx["organizations"]["seller"],
            "planned_pickup_start": delivery["pickup_earliest_at"],
            "planned_pickup_end": delivery["pickup_latest_at"],
            "expected_delivery_at": delivery["delivery_deadline_at"],
            "pickup_contact_name": "Seller",
            "pickup_contact_phone_e164": "+919876543210",
            "delivery_contact_name": "Buyer",
            "delivery_contact_phone_e164": "+919876543210",
            "declared_gross_weight_kg": "400",
            "package_type": "CARTON",
            "package_count": 4,
            "items": [
                {
                    "line_ref": accepted["facts"]["items"][0]["line_ref"],
                    "allocated_quantity": quantity,
                    "uqc": "NOS",
                }
            ],
        }
        return {**body, **changes}

    def allocate(self, quantity="40"):
        return self.call(f"/trades/{self.trade_id}/consignments", self.plan(quantity), expected=201)

    def prepare(self, cn):
        return self.call(
            f"/consignments/{cn['id']}/preparations", {}, etag=self.cn(cn["id"])["etag"]
        )

    def propose(self, cn, **changes):
        return self.call(
            f"/consignments/{cn['id']}/assignments",
            {
                "carrier_organization_id": self.fx["organizations"]["carrier"],
                "booking_start_at": cn["plan_json"]["planned_pickup_start"],
                "booking_end_at": cn["plan_json"]["expected_delivery_at"],
                **changes,
            },
            etag=self.cn(cn["id"])["etag"],
            expected=201,
        )

    def accept(self, assignment, index=0):
        return self.call(
            f"/assignments/{assignment['id']}/decisions",
            {
                "decision": "ACCEPT",
                "vehicle_id": self.fx["vehicles"][index],
                "driver_user_id": self.fx["users"]["driver-one" if index == 0 else "driver-two"],
            },
            user="carrier-dispatcher",
        )

    def event(self, cn, assignment, kind, index=0, **changes):
        guarded = {}
        if kind in {"PICKUP_CONFIRMED", "DEPARTED"}:
            from app.operations.models import Consignment

            with self.sessions() as db:
                row = db.get(Consignment, cn["id"])
                head = context.heads(db, row)
                if not head or not head.current_binding_revision_id:
                    prepared = demo.prepare(db, self.fx, cn["id"])
                    manifest_id = prepared["manifest_id"]
                else:
                    manifest_id = head.current_loading_manifest_revision_id
                token = demo.authorise(db, self.fx, cn["id"], kind)
                db.commit()
            guarded = {"dispatch_authorization_id": token["id"]}
            if kind == "PICKUP_CONFIRMED":
                guarded["loading_manifest_revision_id"] = manifest_id
        payload = {
            "client_event_id": str(uuid4()),
            "assignment_id": assignment["id"],
            "event_type": kind,
            "occurred_at": now().isoformat(),
            "payload": {},
        }
        if kind == "PICKUP_CONFIRMED":
            payload["payload"] = {
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
            }
        return self.call(
            f"/consignments/{cn['id']}/events",
            {**payload, **guarded, **changes},
            user="driver-one" if index == 0 else "driver-two",
            expected=201,
        )

    def arrived(self, quantity="40", index=0):
        cn = self.prepare(self.allocate(quantity))
        assignment = self.accept(self.propose(cn), index)
        for kind in ("PICKUP_CONFIRMED", "DEPARTED", "ARRIVED"):
            self.event(cn, assignment, kind, index)
        return self.cn(cn["id"]), assignment

    def receipt_body(self, cn, quantity):
        return {
            "client_receipt_id": str(uuid4()),
            "received_at": now().isoformat(),
            "lines": [
                {
                    "consignment_item_id": cn["items"][0]["id"],
                    "delivered_quantity": quantity,
                    "uqc": "NOS",
                    "observed_condition": "GOOD",
                }
            ],
        }

    def receive(self, cn, quantity):
        return self.call(
            f"/consignments/{cn['id']}/receipts",
            self.receipt_body(cn, quantity),
            user="buyer-receiver",
            expected=201,
        )

    def inspect(self, receipt, accepted, rejected="0"):
        return self.call(
            f"/receipts/{receipt['id']}/acceptances",
            {
                "decisions": [
                    {
                        "receipt_line_id": receipt["lines"][0]["id"],
                        "accepted_quantity": accepted,
                        "rejected_quantity": rejected,
                        **({"rejection_reason": "QUALITY"} if rejected != "0" else {}),
                    }
                ]
            },
            user="buyer-inspector",
            expected=201,
        )

    def schedule(self):
        candidate = self.call(
            f"/trades/{self.trade_id}/payment-schedule-candidate", user="buyer-finance"
        )
        proposed = self.call(
            f"/trades/{self.trade_id}/payment-schedules",
            {
                "accepted_revision_id": candidate["accepted_revision_id"],
                "lines": candidate["lines"],
            },
            user="buyer-finance",
            etag=self.trade()["etag"],
            expected=201,
        )
        for user in ("buyer-finance", "seller-finance"):
            proposed = self.call(
                f"/payment-schedules/{proposed['id']}/approvals",
                {"decision": "ACCEPT", "content_hash": proposed["content_hash"]},
                user=user,
            )
        return proposed

    def payment(self, amount="1000000", acknowledge=True):
        result = self.call(
            f"/trades/{self.trade_id}/payments",
            {
                "amount_minor": amount,
                "paid_on": now().date().isoformat(),
                "method": "BANK_TRANSFER",
            },
            user="buyer-finance",
            expected=201,
        )
        assert result["status"] == "MANUAL_REPORTED"
        if acknowledge:
            result = self.call(
                f"/payments/{result['id']}/acknowledgements", {}, user="seller-finance"
            )
        return result

    def amendment(self, changes, approve=True, expected=200):
        if "items" in changes:
            changes = {
                **changes,
                "items": [
                    {k: v for k, v in item.items() if k in GoodsLine.model_fields}
                    for item in changes["items"]
                ],
            }
        before = self.trade()
        result = self.call(
            f"/trades/{self.trade_id}/amendments",
            {
                "base_accepted_revision_id": before["accepted_revision"]["id"],
                "reason": "Test revised agreed terms",
            },
            etag=before["etag"],
        )
        ident = result["pending_amendment"]["id"]
        result = self.call(
            f"/amendments/{ident}/draft",
            {
                "base_revision_id": result["current_revision_id"],
                "changes": changes,
            },
            method="PATCH",
            etag=result["etag"],
        )
        if not approve:
            return result
        result = self.call(
            f"/amendments/{ident}/offers",
            {
                "revision_id": result["current_revision_id"],
                "commercial_valid_until": (now() + timedelta(days=30)).isoformat(),
            },
            etag=result["etag"],
        )
        offer = result["active_offer"]
        body = {"revision_id": offer["revision_id"], "terms_hash": offer["terms_hash"]}
        self.call(f"/offers/{offer['id']}/confirmations", body, user="seller-approver")
        return self.call(
            f"/offers/{offer['id']}/confirmations", body, user="buyer-approver", expected=expected
        )


def test_complete_40_60_lifecycle(flow):
    from app.trades.openapi import install_openapi

    install_openapi(flow.client.app)
    document = flow.client.app.openapi()

    def documented(name, value):
        definition = document["components"]["schemas"][f"Operational{name}"]
        assert set(definition["required"]) <= set(value) <= set(definition["properties"])

    correction_headers = document["paths"]["/api/v1/receipts/{ident}/corrections"]["post"][
        "parameters"
    ]
    assert any(h["name"] == "If-Match" and h["required"] for h in correction_headers)
    first, second = flow.allocate("40"), flow.allocate("60")
    documented("Consignment", first)
    assert flow.workspace()["availability"][0]["available_quantity"] == "0.000000"
    assert (
        flow.call(f"/trades/{flow.trade_id}/consignments", flow.plan("1"), expected=409)["error"][
            "code"
        ]
        == "ALLOCATION_CONFLICT"
    )
    for index, cn in enumerate((first, second)):
        cn = flow.prepare(cn)
        assignment = flow.accept(flow.propose(cn), index)
        documented("Assignment", assignment)
        assert assignment["suitability_json"]["volume_assessment"] == "UNKNOWN"
        for kind in ("PICKUP_CONFIRMED", "DEPARTED", "ARRIVED"):
            documented("Event", flow.event(cn, assignment, kind, index))
        for quantity in ["20", "20"] if index == 0 else ["60"]:
            receipt = flow.receive(cn, quantity)
            documented("Receipt", receipt)
            documented("InspectionBatch", flow.inspect(receipt, quantity))
        closure = flow.call(
            f"/consignments/{cn['id']}/delivery-closures",
            {},
            user="buyer-receiver",
            etag=flow.cn(cn["id"])["etag"],
            expected=201,
        )
        assert closure["quantity_summary_json"]["lines"][0]["short_quantity"] == "0.000000"
        documented("Closure", closure)
    schedule = flow.schedule()
    documented("Schedule", schedule)
    assert schedule["status"] == "ACTIVE"
    payment = flow.payment()
    documented("Payment", payment)
    assert payment["status"] == "COUNTERPARTY_ACKNOWLEDGED"
    flow.call(
        f"/payments/{payment['id']}/allocations",
        {
            "allocations": [
                {
                    "obligation_ref": schedule["lines"][0]["obligation_ref"],
                    "amount_minor": "1000000",
                }
            ]
        },
        user="seller-finance",
    )
    result = flow.workspace("seller-finance")
    documented("Workspace", result)
    documented("Settlement", result["settlement"])
    assert result["settlement"]["net_allocated_minor"] == "1000000"
    assert (
        result["dispatch_readiness"]
        == result["settlement"]["provider_verification"]
        == result["settlement"]["final_invoice_reconciliation"]
        == "NOT_ASSESSED"
    )
    assert result["execution_mode"] == "SIMULATION"
    from app.document_desk import access as document_access

    evidence_endpoint = next(r.endpoint for r in flow.client.app.routes if r.name == "evidence")
    assert (
        evidence_endpoint.__globals__["TradeError"]
        is document_access.fail.__globals__["TradeError"]
    ), "Collected service namespace and document access exception types diverged"
    history = flow.call(f"/trades/{flow.trade_id}/evidence-events")
    cursor = history["next_cursor"]
    while cursor:
        page = flow.call(f"/trades/{flow.trade_id}/evidence-events?cursor={cursor}")
        history["items"].extend(page["items"])
        cursor = page["next_cursor"]
    assert {
        "CONSIGNMENT_ALLOCATED",
        "MOVEMENT_EVENT_RECORDED",
        "RECEIPT_RECORDED",
        "INSPECTION_RECORDED",
        "PAYMENT_ALLOCATED",
    } <= {e["action"] for e in history["items"]}
    assert all(e["execution_mode"] == "SIMULATION" for e in history["items"])
    context = flow.call(f"/consignments/{first['id']}/planning-context")
    assert (
        context["schema_version"] == 1
        and context["origin_coordinates"] is None
        and len(context["input_hash"]) == 64
    )


def test_reservations_cancellation_units_and_stale_versions(flow):
    cn = flow.allocate("40")
    path = f"/consignments/{cn['id']}/cancellations"
    assert (
        flow.call(path, {"reason": "release"}, etag='"999"', expected=412)["error"]["code"]
        == "STALE_VERSION"
    )
    cancelled = flow.call(path, {"reason": "release"}, etag=cn["etag"])
    assert cancelled["planning_status"] == "CANCELLED"
    assert flow.workspace()["availability"][0]["available_quantity"] == "100.000000"
    flow.call(path, {"reason": "release again"}, etag=cancelled["etag"], expected=409)
    body = flow.plan("1")
    body["items"][0]["uqc"] = "PCS"
    flow.call(f"/trades/{flow.trade_id}/consignments", body, expected=422)


def test_assignment_capacity_ownership_booking_replacement_and_snapshots(flow):
    cn = flow.prepare(flow.allocate())
    proposal = flow.propose(cn)
    assert proposal["status"] == "PROPOSED" and flow.cn(cn["id"])["active_assignment_id"] is None
    body = {
        "decision": "ACCEPT",
        "vehicle_id": flow.fx["vehicles"][0],
        "driver_user_id": flow.fx["users"]["driver-one"],
    }
    flow.call(f"/assignments/{proposal['id']}/decisions", body, user="unrelated", expected=403)
    wrong = {**body, "driver_user_id": flow.fx["users"]["unrelated"]}
    flow.call(
        f"/assignments/{proposal['id']}/decisions", wrong, user="carrier-dispatcher", expected=403
    )
    vehicles = flow.call(
        f"/organizations/{flow.fx['organizations']['carrier']}/vehicles", user="carrier-dispatcher"
    )["items"]
    vehicle = vehicles[0]
    flow.call(
        f"/vehicles/{vehicle['id']}",
        {"declared_payload_capacity_kg": "100"},
        user="carrier-dispatcher",
        etag=vehicle["etag"],
        method="PATCH",
    )
    flow.call(
        f"/assignments/{proposal['id']}/decisions", body, user="carrier-dispatcher", expected=409
    )
    vehicle = flow.call(
        f"/organizations/{flow.fx['organizations']['carrier']}/vehicles", user="carrier-dispatcher"
    )["items"][0]
    flow.call(
        f"/vehicles/{vehicle['id']}",
        {"declared_payload_capacity_kg": "1000"},
        user="carrier-dispatcher",
        etag=vehicle["etag"],
        method="PATCH",
    )
    accepted = flow.accept(proposal)
    other = flow.prepare(flow.allocate("60"))
    blocked = flow.propose(other)
    flow.call(
        f"/assignments/{blocked['id']}/decisions", body, user="carrier-dispatcher", expected=409
    )
    replacement = flow.accept(flow.propose(cn), 1)
    assert replacement["supersedes_assignment_id"] == accepted["id"]
    flow.call(f"/consignments/{cn['id']}", user="driver-one", expected=404)
    assert not flow.call("/me/transport-tasks", user="driver-one")["items"]
    current = flow.cn(cn["id"])
    assert current["dispatch_readiness"] == "NOT_ASSESSED"
    assert (
        next(a for a in current["assignments"] if a["id"] == accepted["id"])["vehicle_snapshot"][
            "declared_payload_capacity_kg"
        ]
        == "1000"
    )


def test_movement_event_identity_late_location_and_handover(flow):
    cn = flow.prepare(flow.allocate())
    assignment = flow.accept(flow.propose(cn))
    body = {
        "client_event_id": str(uuid4()),
        "event_type": "DEPARTED",
        "assignment_id": assignment["id"],
        "occurred_at": now().isoformat(),
        "payload": {},
    }
    flow.call(f"/consignments/{cn['id']}/events", body, user="driver-one", expected=409)
    flow.event(cn, assignment, "PICKUP_CONFIRMED")
    from app.compliance import demo as compliance_demo

    with flow.sessions() as db:
        token = compliance_demo.authorise(db, flow.fx, cn["id"], "DEPARTED")
        db.commit()
    body["dispatch_authorization_id"] = token["id"]
    first = flow.call(f"/consignments/{cn['id']}/events", body, user="driver-one", expected=201)
    duplicate = flow.call(f"/consignments/{cn['id']}/events", body, user="driver-one", expected=201)
    assert first["id"] == duplicate["id"]
    flow.call(
        f"/consignments/{cn['id']}/events",
        {**body, "notes": "changed"},
        user="driver-one",
        expected=409,
    )
    flow.event(cn, assignment, "LOCATION_REPORTED", latitude="12", longitude="77")
    late = flow.event(
        cn,
        assignment,
        "LOCATION_REPORTED",
        latitude="11",
        longitude="76",
        occurred_at=(now() - timedelta(hours=1)).isoformat(),
    )
    assert (
        not late["projection_applied"]
        and flow.cn(cn["id"])["latest_location_json"]["latitude"] == "12"
    )
    flow.event(cn, assignment, "ARRIVED")
    flow.event(cn, assignment, "DELIVERY_HANDOVER_REPORTED")
    result = flow.cn(cn["id"])
    assert (
        result["movement_status"] == "ARRIVED"
        and result["current_delivery_closure_id"] is None
        and result["receipt_summary"][0]["accepted_quantity"] == "0.000000"
    )
    flow.call(
        f"/consignments/{cn['id']}/cancellations",
        {"reason": "picked"},
        etag=result["etag"],
        expected=409,
    )


def test_incremental_receipt_inspection_correction_reopen_and_rejection(flow):
    cn, _ = flow.arrived("60")
    first = flow.receive(cn, "20")
    assert flow.cn(cn["id"])["receipt_summary"][0]["awaiting_receipt_quantity"] == "40.000000"
    assert flow.cn(cn["id"])["receipt_summary"][0]["short_quantity"] == "0.000000"
    flow.receive(cn, "37")
    flow.call(
        f"/consignments/{cn['id']}/receipts",
        flow.receipt_body(cn, "4"),
        user="buyer-receiver",
        expected=409,
    )
    decision = flow.inspect(first, "19", "1")["decisions"][0]
    flow.call(
        f"/receipts/{first['id']}/acceptances",
        {
            "decisions": [
                {
                    "receipt_line_id": first["lines"][0]["id"],
                    "accepted_quantity": "1",
                    "rejected_quantity": "0",
                }
            ]
        },
        user="buyer-inspector",
        expected=409,
    )
    correction = {**flow.receipt_body(cn, "19"), "reason": "recount"}
    flow.call(
        f"/receipts/{first['id']}/corrections",
        correction,
        user="buyer-receiver",
        etag=first["head_etag"],
        expected=409,
    )
    closure = flow.call(
        f"/consignments/{cn['id']}/delivery-closures",
        {},
        user="buyer-receiver",
        etag=flow.cn(cn["id"])["etag"],
        expected=201,
    )
    assert closure["quantity_summary_json"]["lines"][0]["short_quantity"] == "3.000000"
    flow.call(
        f"/inspection-decisions/{decision['id']}/reversals",
        {"reason": "inspect again"},
        user="buyer-inspector",
        expected=201,
    )
    flow.call(
        f"/receipts/{first['id']}/corrections",
        correction,
        user="buyer-receiver",
        etag=first["head_etag"],
        expected=409,
    )
    flow.call(
        f"/delivery-closures/{closure['id']}/reopenings",
        {"reason": "recount"},
        user="buyer-receiver",
        etag=flow.cn(cn["id"])["etag"],
        expected=201,
    )
    replacement = flow.call(
        f"/receipts/{first['id']}/corrections",
        correction,
        user="buyer-receiver",
        etag=first["head_etag"],
        expected=201,
    )
    assert replacement["supersedes_receipt_id"] == first["id"]
    assert flow.cn(cn["id"])["receipt_summary"][0]["received_quantity"] == "56.000000"
    reclose = flow.call(
        f"/consignments/{cn['id']}/delivery-closures",
        {},
        user="buyer-receiver",
        etag=flow.cn(cn["id"])["etag"],
        expected=201,
    )
    assert reclose["id"] != closure["id"] and len(flow.cn(cn["id"])["closures"]) == 2
    assert flow.workspace()["availability"][0]["available_quantity"] == "40.000000"


def test_bilateral_dispute_does_not_mutate_goods(flow):
    cn = flow.allocate()
    dispute = flow.call(
        f"/trades/{flow.trade_id}/disputes",
        {"consignment_id": cn["id"], "dispute_type": "OTHER", "summary": "Agree next action"},
        expected=201,
    )
    flow.call(f"/disputes/{dispute['id']}", user="unrelated", expected=404)
    proposal = flow.call(
        f"/disputes/{dispute['id']}/resolution-proposals",
        {"outcome": "RETURN_REQUESTED", "resolution_text": "Review a future return"},
    )
    body = {"proposal_id": proposal["active_proposal_id"], "decision": "ACCEPT"}
    assert (
        flow.call(f"/disputes/{dispute['id']}/resolution-decisions", body)["status"]
        == "RESOLUTION_PROPOSED"
    )
    assert (
        flow.call(f"/disputes/{dispute['id']}/resolution-decisions", body, user="buyer-receiver")[
            "status"
        ]
        == "RESOLVED"
    )
    assert (
        flow.cn(cn["id"])["movement_status"] == "NOT_STARTED"
        and flow.workspace()["availability"][0]["available_quantity"] == "60.000000"
    )


def test_payment_report_ack_allocation_reversal_bilateral_void(flow):
    schedule = flow.schedule()
    payment = flow.payment(acknowledge=False)
    batch = {
        "allocations": [
            {"obligation_ref": schedule["lines"][0]["obligation_ref"], "amount_minor": "600000"}
        ]
    }
    flow.call(f"/payments/{payment['id']}/allocations", batch, user="seller-finance", expected=409)
    flow.call(
        f"/payments/{payment['id']}/acknowledgements", {}, user="seller-operations", expected=403
    )
    flow.call(f"/payments/{payment['id']}/acknowledgements", {}, user="seller-finance")
    allocated = flow.call(f"/payments/{payment['id']}/allocations", batch, user="seller-finance")
    original = allocated["allocations"][0]
    flow.call(
        f"/payments/{payment['id']}/withdrawals",
        {"reason": "cannot"},
        user="buyer-finance",
        expected=409,
    )
    flow.call(
        f"/payment-allocations/{original['id']}/reversals",
        {"amount_minor": "600001", "reason": "too much"},
        user="seller-finance",
        expected=409,
    )
    flow.call(
        f"/payment-allocations/{original['id']}/reversals",
        {"amount_minor": "100000", "reason": "correct entry"},
        user="seller-finance",
    )
    requested = flow.call(
        f"/payments/{payment['id']}/void-requests",
        {"reason": "Incorrect record, no refund"},
        user="buyer-finance",
    )
    assert (
        requested["status"] == "COUNTERPARTY_ACKNOWLEDGED"
        and requested["net_allocated_minor"] == "500000"
    )
    body = {"void_request_id": requested["pending_void_request"]["id"], "decision": "APPROVE"}
    flow.call(f"/payments/{payment['id']}/void-decisions", body, user="buyer-finance", expected=403)
    void = flow.call(f"/payments/{payment['id']}/void-decisions", body, user="seller-finance")
    assert void["status"] == "VOID" and void["net_allocated_minor"] == "0"
    assert not flow.workspace()["consignments"]


@pytest.mark.parametrize(
    "user,path",
    [
        ("driver-one", "settlement"),
        ("carrier-dispatcher", "operations"),
        ("unrelated", "operations"),
    ],
)
def test_financial_and_trade_isolation(flow, user, path):
    flow.call(f"/trades/{flow.trade_id}/{path}", user=user, expected=404)


def test_idempotency_immutable_ledgers_and_quarantine(flow):
    key = str(uuid4())
    body = flow.plan()
    a = flow.call(f"/trades/{flow.trade_id}/consignments", body, key=key, expected=201)
    b = flow.call(f"/trades/{flow.trade_id}/consignments", body, key=key, expected=201)
    assert a == b
    flow.call(f"/trades/{flow.trade_id}/consignments", flow.plan("41"), key=key, expected=409)
    with flow.sessions() as db:
        assert (
            len(list(db.scalars(select(Audit).where(Audit.action == "CONSIGNMENT_ALLOCATED")))) == 1
        )
        with pytest.raises(DBAPIError):
            db.execute(
                update(Trade).where(Trade.id == flow.trade_id).values(execution_mode="PRODUCTION")
            )
        db.rollback()
    upload = flow.call(
        "/operational-attachments/uploads",
        {
            "trade_id": flow.trade_id,
            "purpose": "OTHER",
            "original_name": "test.pdf",
            "content_type": "application/pdf",
            "size_bytes": 8,
        },
        expected=201,
    )
    flow.call(f"/operational-attachments/{upload['id']}/download", expected=403)


def test_largest_remainder_rounding():
    assert amounts(23, ["30", "70"]) == [7, 16]
    assert amounts(1, ["50", "50"]) == [1, 0]


def test_capacity_risk_links_to_declared_proposal_without_granting_acceptance(flow):
    cn = flow.prepare(flow.allocate())
    vehicle = flow.call(
        f"/organizations/{flow.fx['organizations']['carrier']}/vehicles",
        user="carrier-dispatcher",
    )["items"][0]
    flow.call(
        f"/vehicles/{vehicle['id']}",
        {"declared_payload_capacity_kg": "100"},
        user="carrier-dispatcher",
        method="PATCH",
        etag=vehicle["etag"],
    )
    proposal = flow.propose(cn, vehicle_id=vehicle["id"])
    risk = next(
        r for r in flow.workspace()["exceptions"] if r["type"] == "DECLARED_CAPACITY_EXCEEDED"
    )
    assert risk["source_id"] == proposal["id"]
    assert risk["consignment_id"] == cn["id"]
    assert risk["fact_status"] == "DECLARED" and risk["verification_status"] == "NOT_ASSESSED"
    assert flow.cn(cn["id"])["active_assignment_id"] is None
    assert flow.workspace()["dispatch_readiness"] == "NOT_ASSESSED"


def test_driver_uploads_and_reads_only_assigned_nonfinancial_evidence(flow):
    cn = flow.prepare(flow.allocate())
    assignment = flow.accept(flow.propose(cn))
    body = {
        "trade_id": flow.trade_id,
        "consignment_id": cn["id"],
        "purpose": "PICKUP",
        "original_name": "pickup.png",
        "content_type": "image/png",
        "size_bytes": 8,
    }
    uploaded = flow.call("/operational-attachments/uploads", body, user="driver-one", expected=201)
    task = flow.call(f"/assignments/{assignment['id']}", user="driver-one")
    assert [a["id"] for a in task["consignment"]["documents"]] == [uploaded["id"]]
    assert "object_key" not in task["consignment"]["documents"][0]
    flow.call("/operational-attachments/uploads", body, user="driver-two", expected=404)
    payment = flow.call(
        "/operational-attachments/uploads",
        {**body, "purpose": "PAYMENT"},
        user="seller-finance",
        expected=201,
    )
    assert [a["id"] for a in flow.cn(cn["id"], "driver-one")["documents"]] == [uploaded["id"]]
    flow.call(f"/operational-attachments/{payment['id']}", user="driver-one", expected=403)
    assert len(flow.cn(cn["id"], "seller-finance")["documents"]) == 2


@pytest.mark.parametrize("change", ["quantity", "uqc", "remove"])
def test_allocated_amendment_fails_atomically(flow, change):
    flow.allocate("100")
    before = flow.trade()["accepted_revision"]["id"]
    goods = deepcopy(flow.trade()["accepted_revision"]["facts"]["items"])
    if change == "remove":
        goods[0].pop("line_ref")
    else:
        goods[0][change] = "99" if change == "quantity" else "KGS"
    result = flow.amendment({"items": goods}, expected=409)
    assert result["error"]["code"] == "ALLOCATION_CONFLICT"
    assert flow.trade()["accepted_revision"]["id"] == before
    assert flow.workspace()["availability"][0]["reserved_quantity"] == "100.000000"


def test_pending_and_accepted_revision_reservations_and_material_snapshots(flow):
    cn = flow.allocate("40")
    goods = deepcopy(flow.trade()["accepted_revision"]["facts"]["items"])
    goods[0]["quantity"] = "110"
    draft = flow.amendment({"items": goods}, approve=False)
    assert flow.workspace()["availability"][0]["available_quantity"] == "60.000000"
    ident = draft["pending_amendment"]["id"]
    result = flow.call(
        f"/amendments/{ident}/offers",
        {
            "revision_id": draft["current_revision_id"],
            "commercial_valid_until": (now() + timedelta(days=30)).isoformat(),
        },
        etag=draft["etag"],
    )
    offer = result["active_offer"]
    for side in ("seller", "buyer"):
        flow.call(
            f"/offers/{offer['id']}/confirmations",
            {
                "revision_id": offer["revision_id"],
                "terms_hash": offer["terms_hash"],
            },
            user=f"{side}-approver",
        )
    second = flow.allocate("70")
    assert second["source_accepted_revision_id"] != cn["source_accepted_revision_id"]
    assert flow.workspace()["availability"][0]["available_quantity"] == "0.000000"
    goods[0]["description"] = "Revised goods description"
    flow.amendment({"items": goods})
    after = flow.cn(cn["id"])
    assert after["revision_alignment"] == "REVIEW_REQUIRED"
    assert after["items"][0]["description_snapshot"] == cn["items"][0]["description_snapshot"]
    flow.call(f"/consignments/{cn['id']}/preparations", {}, etag=after["etag"], expected=409)


@pytest.mark.parametrize("kind", ["PICKUP_CONFIRMED", "DEPARTED", "ARRIVED"])
def test_production_gate_and_server_owned_fields(flow, kind):
    with flow.sessions() as db:
        production = seed_demo(
            db, subjects=flow.fx["subjects"], namespace="production", production=True
        )
    original = flow.fx
    flow.fx, flow.trade_id = production, production["trade_id"]
    cn = flow.prepare(flow.allocate())
    assignment = flow.accept(flow.propose(cn))
    payload = {
        "client_event_id": str(uuid4()),
        "assignment_id": assignment["id"],
        "event_type": kind,
        "occurred_at": now().isoformat(),
        "payload": {},
    }
    if kind == "PICKUP_CONFIRMED":
        payload["payload"] = {
            "items": [
                {"consignment_item_id": cn["items"][0]["id"], "loaded_quantity": "40", "uqc": "NOS"}
            ],
            "actual_gross_weight_kg": "400",
            "actual_package_count": 4,
        }
    response = flow.call(
        f"/consignments/{cn['id']}/events", payload, user="driver-one", expected=409
    )
    assert response["error"]["code"] == (
        "COMPLIANCE_NOT_READY" if kind == "PICKUP_CONFIRMED" else "INVALID_MOVEMENT_TRANSITION"
    )
    flow.call(
        f"/consignments/{cn['id']}",
        {"execution_mode": "SIMULATION"},
        method="PATCH",
        etag=cn["etag"],
        expected=422,
    )
    payload["status"] = "ARRIVED"
    flow.call(f"/consignments/{cn['id']}/events", payload, user="driver-one", expected=422)
    assert flow.cn(cn["id"])["movement_status"] == "NOT_STARTED"
    flow.fx = original


def test_receipt_identity_and_acceptance_authority(flow):
    cn, _ = flow.arrived()
    body = flow.receipt_body(cn, "40")
    first = flow.call(
        f"/consignments/{cn['id']}/receipts", body, user="buyer-receiver", expected=201
    )
    assert (
        first["id"]
        == flow.call(
            f"/consignments/{cn['id']}/receipts", body, user="buyer-receiver", expected=201
        )["id"]
    )
    body["lines"][0]["delivered_quantity"] = "39"
    flow.call(f"/consignments/{cn['id']}/receipts", body, user="buyer-receiver", expected=409)
    assert flow.cn(cn["id"])["receipt_summary"][0]["inspection_status"] == "PENDING_INSPECTION"
    decisions = {
        "decisions": [
            {
                "receipt_line_id": first["lines"][0]["id"],
                "accepted_quantity": "40",
                "rejected_quantity": "0",
            }
        ]
    }
    for user in ("driver-one", "carrier-dispatcher", "buyer-receiver"):
        flow.call(f"/receipts/{first['id']}/acceptances", decisions, user=user, expected=403)
    inspected = flow.inspect(first, "40")["decisions"][0]
    with flow.sessions() as db:
        with pytest.raises(DBAPIError):
            db.execute(
                update(Inspection)
                .where(Inspection.id == inspected["id"])
                .values(accepted_quantity=0)
            )
        db.rollback()


def test_full_delivery_rejection_and_trigger_retraction_preserve_due_history(flow):
    schedule = flow.schedule()
    cn, assignment = flow.arrived("100")
    receipt = flow.receive(cn, "100")
    decision = flow.inspect(receipt, "99", "1")["decisions"][0]
    settlement = flow.workspace("seller-finance")["settlement"]
    obligation = settlement["obligations"][0]
    assert obligation["trigger_met"]
    assert not any(
        t["trigger"] == "FULL_ACCEPTANCE" and t["event_kind"] == "ACTIVATED"
        for t in settlement["trigger_history"]
    )
    original_due = obligation["due_on"]
    flow.call(
        f"/inspection-decisions/{decision['id']}/reversals",
        {"reason": "Recount"},
        user="buyer-inspector",
        expected=201,
    )
    flow.call(
        f"/receipts/{receipt['id']}/corrections",
        {**flow.receipt_body(cn, "99"), "reason": "Recount"},
        user="buyer-receiver",
        etag=receipt["head_etag"],
        expected=201,
    )
    settlement = flow.workspace("seller-finance")["settlement"]
    assert not settlement["obligations"][0]["trigger_met"]
    assert settlement["obligations"][0]["due_on"] == original_due
    assert settlement["schedule_review_required"]
    assert any(t["event_kind"] == "RETRACTED" for t in settlement["trigger_history"])
    assert schedule["status"] == "ACTIVE" and assignment["status"] == "ACCEPTED"


@pytest.mark.parametrize("mode", ["ADVANCE", "CREDIT"])
def test_ambiguous_terms_need_bilateral_clarification(flow, mode):
    terms = deepcopy(flow.trade()["accepted_revision"]["facts"]["commercial_terms"])
    terms["payment_mode"] = mode
    terms["advance_minor"] = "200000" if mode == "ADVANCE" else None
    terms["credit_days"] = 30 if mode == "CREDIT" else None
    flow.amendment({"commercial_terms": terms})
    candidate = flow.call(
        f"/trades/{flow.trade_id}/payment-schedule-candidate", user="buyer-finance"
    )
    assert candidate["status"] == "NEEDS_CLARIFICATION" and candidate["questions"]


def test_payment_hash_stale_approvals_and_revoked_replay(flow):
    candidate = flow.call(
        f"/trades/{flow.trade_id}/payment-schedule-candidate", user="buyer-finance"
    )
    proposal = flow.call(
        f"/trades/{flow.trade_id}/payment-schedules",
        {"accepted_revision_id": candidate["accepted_revision_id"], "lines": candidate["lines"]},
        user="buyer-finance",
        etag=flow.trade()["etag"],
        expected=201,
    )
    flow.call(
        f"/payment-schedules/{proposal['id']}/approvals",
        {"decision": "ACCEPT", "content_hash": "0" * 64},
        user="buyer-finance",
        expected=409,
    )
    flow.amendment({"tax_terms": "Updated tax declaration"})
    flow.call(
        f"/payment-schedules/{proposal['id']}/approvals",
        {"decision": "ACCEPT", "content_hash": proposal["content_hash"]},
        user="seller-finance",
        expected=409,
    )
    with flow.sessions() as db:
        with pytest.raises(DBAPIError):
            db.execute(
                update(Schedule).where(Schedule.id == proposal["id"]).values(content_hash="0" * 64)
            )
        db.rollback()
    key = str(uuid4())
    plan = flow.plan()
    flow.call(f"/trades/{flow.trade_id}/consignments", plan, key=key, expected=201)
    with flow.sessions() as db:
        member = db.scalar(
            select(Membership).where(Membership.user_id == flow.fx["users"]["seller-operations"])
        )
        for grant in db.scalars(
            select(Grant).where(
                Grant.membership_id == member.id, Grant.permission_code == "consignment.plan"
            )
        ):
            grant.revoked_at = now()
        db.commit()
    flow.call(f"/trades/{flow.trade_id}/consignments", plan, key=key, expected=403)


def test_disputed_payment_and_atomic_allocation_batch(flow):
    schedule = flow.schedule()
    payment = flow.payment()
    flow.call(
        f"/payments/{payment['id']}/disputes",
        {"reason": "Reference mismatch"},
        user="seller-finance",
    )
    batch = {
        "allocations": [
            {"obligation_ref": schedule["lines"][0]["obligation_ref"], "amount_minor": "1"}
        ]
    }
    flow.call(f"/payments/{payment['id']}/allocations", batch, user="seller-finance", expected=409)
    payment = flow.payment()
    batch["allocations"].append({"obligation_ref": str(uuid4()), "amount_minor": "1"})
    flow.call(f"/payments/{payment['id']}/allocations", batch, user="seller-finance", expected=422)
    assert flow.workspace("seller-finance")["settlement"]["net_allocated_minor"] == "0"


@pytest.mark.parametrize(
    "scenario",
    [
        "complete",
        "capacity",
        "short",
        "rejected",
        "correction",
        "carrier-access",
        "payment-dispute",
        "overapplied",
    ],
)
def test_development_scenarios_use_real_domain_invariants(flow, scenario):
    result = Demo(flow.sessions, flow.fx).scenario(scenario)
    assert result["execution_mode"] == "SIMULATION"
    if scenario == "overapplied":
        assert result["settlement"]["overapplied_minor"] == "200000"
        assert result["settlement"]["net_allocated_minor"] == "1000000"
    if scenario == "complete":
        assert result["settlement"]["net_allocated_minor"] == "1000000"


@pytest.mark.parametrize("kind", ["allocation", "booking", "inspection", "payment", "obligation"])
def test_postgres_concurrent_limits(flow, kind):
    if not flow.postgres:
        pytest.skip("Set TRADE_TEST_DATABASE_URL to exercise PostgreSQL row-lock races")
    if kind == "allocation":

        def run(index):
            return flow.call(
                f"/trades/{flow.trade_id}/consignments", flow.plan("60"), expected=None
            )
    elif kind == "booking":
        assignments = [flow.propose(flow.prepare(flow.allocate("50"))) for _ in range(2)]

        def run(index):
            return flow.call(
                f"/assignments/{assignments[index]['id']}/decisions",
                {
                    "decision": "ACCEPT",
                    "vehicle_id": flow.fx["vehicles"][0],
                    "driver_user_id": flow.fx["users"]["driver-one"],
                },
                user="carrier-dispatcher",
                expected=None,
            )
    elif kind == "inspection":
        cn, _ = flow.arrived()
        receipt = flow.receive(cn, "40")

        def run(index):
            return flow.call(
                f"/receipts/{receipt['id']}/acceptances",
                {
                    "decisions": [
                        {
                            "receipt_line_id": receipt["lines"][0]["id"],
                            "accepted_quantity": "30",
                            "rejected_quantity": "0",
                        }
                    ]
                },
                user="buyer-inspector",
                expected=None,
            )
    else:
        schedule = flow.schedule()
        payments = [flow.payment() for _ in range(2)]

        def run(index):
            return flow.call(
                f"/payments/{payments[0 if kind == 'payment' else index]['id']}/allocations",
                {
                    "allocations": [
                        {
                            "obligation_ref": schedule["lines"][0]["obligation_ref"],
                            "amount_minor": "600000",
                        }
                    ]
                },
                user="seller-finance",
                expected=None,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (0, 1)))
    assert sorted(r.status_code for r in results) in ([201, 409], [200, 409]), [
        r.text for r in results
    ]
