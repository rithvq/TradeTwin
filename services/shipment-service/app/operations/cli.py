"""Explicit development harness; no public reset or authentication bypass."""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal, engine
from app.trades import agreements
from app.trades.errors import TradeError
from app.trades.ledger import revision_facts
from app.trades.migrate import migrate
from app.trades.models import Revision, Trade, User, now, uid
from app.trades.schemas import AmendmentCreate, Confirmation, DraftPatch, GoodsLine, Publish
from app.trades.transactions import Context

from . import allocation, movement, payments, receiving, schedules, transport, views
from .demo import ROLES, seed_demo
from .models import Consignment, Vehicle
from .schemas import (
    AssignmentDecision,
    AssignmentProposal,
    ConsignmentPlan,
    InspectionBatch,
    Notes,
    PaymentAllocationBatch,
    PaymentInput,
    PaymentScheduleInput,
    Reason,
    ReceiptCorrection,
    ReceiptInput,
    ScheduleApproval,
    ShipmentEventInput,
    VehiclePatch,
)


class Demo:
    def __init__(self, sessions, fixtures):
        self.sessions, self.fx = sessions, fixtures
        self.trade_id = fixtures["trade_id"]

    def run(self, role, action, model, body, ident=None, resource=None, etag=None):
        with self.sessions() as db:
            ctx = Context(
                db.get(User, self.fx["users"][role]),
                self.fx["organizations"][ROLES[role][0]],
                uid(),
            )
            ctx.if_match = f'"{db.get(Trade, self.trade_id).row_version}"'
            if resource:
                row = db.get(resource, ident)
                ctx.if_match = f'"{row.row_version}"'
            if etag:
                ctx.if_match = etag
            payload = model.model_validate(body)
            result = action(db, ctx, ident, payload) if ident else action(db, ctx, payload)
            db.commit()
            return result

    def read(self):
        with self.sessions() as db:
            ctx = Context(
                db.get(User, self.fx["users"]["seller-finance"]),
                self.fx["organizations"]["seller"],
                uid(),
            )
            return views.workspace(db, ctx, db.get(Trade, self.trade_id))

    def allocate(self, quantity):
        with self.sessions() as db:
            trade = db.get(Trade, self.trade_id)
            revision = db.get(Revision, trade.accepted_revision_id)
            facts = revision_facts(db, revision)
        delivery = facts["delivery_requirements"]
        return self.run(
            "seller-operations",
            allocation.create,
            ConsignmentPlan,
            {
                "source_accepted_revision_id": revision.id,
                "coordinating_organization_id": self.fx["organizations"]["seller"],
                "planned_pickup_start": delivery["pickup_earliest_at"],
                "planned_pickup_end": delivery["pickup_latest_at"],
                "expected_delivery_at": delivery["delivery_deadline_at"],
                "pickup_contact_name": "Demo seller",
                "pickup_contact_phone_e164": "+919876543210",
                "delivery_contact_name": "Demo buyer",
                "delivery_contact_phone_e164": "+919876543210",
                "declared_gross_weight_kg": "400",
                "package_type": "CARTON",
                "package_count": 4,
                "items": [
                    {
                        "line_ref": facts["items"][0]["line_ref"],
                        "allocated_quantity": quantity,
                        "uqc": "NOS",
                    }
                ],
            },
            self.trade_id,
        )

    def assignment(self, cn, index):
        self.run("seller-operations", allocation.transition, Notes, {}, cn["id"], Consignment)
        proposal = self.run(
            "seller-operations",
            transport.propose,
            AssignmentProposal,
            {
                "carrier_organization_id": self.fx["organizations"]["carrier"],
                "booking_start_at": cn["plan_json"]["planned_pickup_start"],
                "booking_end_at": cn["plan_json"]["expected_delivery_at"],
            },
            cn["id"],
            Consignment,
        )
        return self.run(
            "carrier-dispatcher",
            transport.decide,
            AssignmentDecision,
            {
                "decision": "ACCEPT",
                "vehicle_id": self.fx["vehicles"][index],
                "driver_user_id": self.fx["users"]["driver-one" if index == 0 else "driver-two"],
            },
            proposal["id"],
        )

    def arrive(self, cn, index=0):
        assignment = self.assignment(cn, index)
        start = datetime.fromisoformat(cn["plan_json"]["planned_pickup_start"])
        finish = datetime.fromisoformat(cn["plan_json"]["expected_delivery_at"])
        for kind in ("PICKUP_CONFIRMED", "DEPARTED", "ARRIVED"):
            payload = (
                {
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
                if kind == "PICKUP_CONFIRMED"
                else {}
            )
            self.run(
                "driver-one" if index == 0 else "driver-two",
                movement.event,
                ShipmentEventInput,
                {
                    "client_event_id": uid(),
                    "assignment_id": assignment["id"],
                    "event_type": kind,
                    "occurred_at": (finish if kind == "ARRIVED" else start),
                    "payload": payload,
                },
                cn["id"],
            )

    def receipt(self, cn, quantity):
        return self.run(
            "buyer-receiver",
            receiving.receive,
            ReceiptInput,
            {
                "client_receipt_id": uid(),
                "received_at": cn["plan_json"]["expected_delivery_at"],
                "lines": [
                    {
                        "consignment_item_id": cn["items"][0]["id"],
                        "delivered_quantity": quantity,
                        "uqc": "NOS",
                        "observed_condition": "GOOD",
                    }
                ],
            },
            cn["id"],
        )

    def inspect(self, receipt, accepted, rejected="0"):
        return self.run(
            "buyer-inspector",
            receiving.inspect_goods,
            InspectionBatch,
            {
                "decisions": [
                    {
                        "receipt_line_id": receipt["lines"][0]["id"],
                        "accepted_quantity": accepted,
                        "rejected_quantity": rejected,
                        "rejection_reason": "QUALITY" if rejected != "0" else None,
                    }
                ],
            },
            receipt["id"],
        )

    def close(self, cn):
        return self.run("buyer-receiver", receiving.close, Notes, {}, cn["id"], Consignment)

    def schedule(self, retained=None):
        with self.sessions() as db:
            generated = schedules.candidate(db, db.get(Trade, self.trade_id))
        if retained:
            generated["lines"][0]["obligation_ref"] = retained
        schedule = self.run(
            "buyer-finance",
            schedules.propose,
            PaymentScheduleInput,
            {
                "accepted_revision_id": generated["accepted_revision_id"],
                "lines": generated["lines"],
                "reason": "Demo replacement retaining funded obligation" if retained else None,
            },
            self.trade_id,
            Trade,
        )
        for role in ("buyer-finance", "seller-finance"):
            schedule = self.run(
                role,
                schedules.approve,
                ScheduleApproval,
                {
                    "decision": "ACCEPT",
                    "content_hash": schedule["content_hash"],
                },
                schedule["id"],
            )
        return schedule

    def payment(self, schedule, dispute=False):
        payment = self.run(
            "buyer-finance",
            payments.report,
            PaymentInput,
            {
                "amount_minor": "1000000",
                "paid_on": now().date(),
                "method": "BANK_TRANSFER",
                "declared_reference": "DEMO-MANUAL-NOT-BANK-VERIFIED",
            },
            self.trade_id,
        )
        self.run(
            "seller-finance",
            lambda db, ctx, ident, body: payments.decide(
                db, ctx, ident, body, "DISPUTE" if dispute else "ACKNOWLEDGE"
            ),
            Reason if dispute else Notes,
            {"reason": "Provider not verified"} if dispute else {},
            payment["id"],
        )
        if not dispute:
            self.run(
                "seller-finance",
                payments.allocate,
                PaymentAllocationBatch,
                {
                    "allocations": [
                        {
                            "obligation_ref": schedule["lines"][0]["obligation_ref"],
                            "amount_minor": "1000000",
                        }
                    ],
                },
                payment["id"],
            )

    def reprice(self):
        with self.sessions() as db:
            accepted = db.get(Trade, self.trade_id).accepted_revision_id
            facts = revision_facts(db, db.get(Revision, accepted))
        result = self.run(
            "seller-operations",
            agreements.create_amendment,
            AmendmentCreate,
            {
                "base_accepted_revision_id": accepted,
                "reason": "Demonstrate reduced goods price",
            },
            self.trade_id,
            Trade,
        )
        amendment = result["pending_amendment"]["id"]
        goods = facts["items"]
        goods = [
            {key: value for key, value in item.items() if key in GoodsLine.model_fields}
            for item in goods
        ]
        goods[0]["unit_price_minor"] = "8000"
        result = self.run(
            "seller-operations",
            lambda db, ctx, ident, body: agreements.patch_draft(
                db, ctx, self.trade_id, body, ident
            ),
            DraftPatch,
            {"base_revision_id": result["current_revision_id"], "changes": {"items": goods}},
            amendment,
        )
        result = self.run(
            "seller-operations",
            lambda db, ctx, ident, body: agreements.publish(db, ctx, self.trade_id, body, ident),
            Publish,
            {
                "revision_id": result["current_revision_id"],
                "commercial_valid_until": facts["commercial_terms"]["commercial_valid_until"],
            },
            amendment,
        )
        offer = result["active_offer"]
        for side in ("seller", "buyer"):
            self.run(
                f"{side}-approver",
                lambda db, ctx, ident, body: agreements.decide(db, ctx, ident, body, "ACCEPT"),
                Confirmation,
                {"revision_id": offer["revision_id"], "terms_hash": offer["terms_hash"]},
                offer["id"],
            )

    def scenario(self, name):
        if name == "double-allocation":
            with self.sessions() as db:
                if db.bind.dialect.name != "postgresql":
                    raise SystemExit("The double-allocation race fixture requires PostgreSQL.")

            def attempt(index):
                try:
                    self.allocate("60")
                    return "RESERVED"
                except TradeError as error:
                    return error.code

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(attempt, (0, 1)))
            assert sorted(results) == ["ALLOCATION_CONFLICT", "RESERVED"], results
            return self.read()
        consignments = [self.allocate("40"), self.allocate("60")]
        try:
            self.allocate("1")
        except TradeError as error:
            assert error.code == "ALLOCATION_CONFLICT"
        if name == "capacity":
            self.run(
                "carrier-dispatcher",
                lambda db, ctx, ident, body: transport.vehicle(db, ctx, body, ident),
                VehiclePatch,
                {"declared_payload_capacity_kg": "100"},
                self.fx["vehicles"][0],
                Vehicle,
            )
            try:
                self.assignment(consignments[0], 0)
            except TradeError as error:
                assert error.code == "CAPACITY_CONFLICT"
            return self.read()
        if name == "carrier-access":
            self.assignment(consignments[0], 0)
            with self.sessions() as db:
                ctx = Context(
                    db.get(User, self.fx["users"]["unrelated"]),
                    self.fx["organizations"]["unrelated"],
                    uid(),
                )
                try:
                    allocation.consignment(db, ctx, consignments[0]["id"])
                    raise AssertionError("Unrelated carrier unexpectedly authorized")
                except TradeError:
                    pass
            return self.read()
        for index, cn in enumerate(consignments):
            self.arrive(cn, index)
            for quantity in ["20", "20"] if index == 0 else ["57" if name == "short" else "60"]:
                receipt = self.receipt(cn, quantity)
                if name == "correction" and index == 0:
                    receipt = self.run(
                        "buyer-receiver",
                        lambda db, ctx, ident, body, cn_id=cn["id"]: receiving.receive(
                            db, ctx, cn_id, body, ident
                        ),
                        ReceiptCorrection,
                        {
                            "client_receipt_id": uid(),
                            "received_at": cn["plan_json"]["expected_delivery_at"],
                            "reason": "Correct count before inspection",
                            "lines": [
                                {
                                    "consignment_item_id": cn["items"][0]["id"],
                                    "delivered_quantity": "19",
                                    "uqc": "NOS",
                                    "observed_condition": "GOOD",
                                }
                            ],
                        },
                        receipt["id"],
                        etag=receipt["head_etag"],
                    )
                    self.inspect(receipt, "19")
                elif name == "rejected":
                    self.inspect(receipt, "0", quantity)
                else:
                    self.inspect(receipt, quantity)
            self.close(cn)
        schedule = self.schedule()
        self.payment(schedule, name == "payment-dispute")
        if name == "overapplied":
            self.reprice()
            self.schedule(schedule["lines"][0]["obligation_ref"])
        return self.read()


def main():
    parser = argparse.ArgumentParser(
        description="Seed/reset SIMULATION fixtures; preserve all history"
    )
    parser.add_argument("--namespace", default="phase2")
    parser.add_argument(
        "--reset", action="store_true", help="Create a fresh namespace, never delete records"
    )
    parser.add_argument("--identity-map", help="JSON role-to-existing-OAuth-profile-ID mapping")
    parser.add_argument(
        "--scenario",
        choices=[
            "ready",
            "complete",
            "capacity",
            "short",
            "rejected",
            "correction",
            "carrier-access",
            "payment-dispute",
            "overapplied",
            "double-allocation",
        ],
        default="ready",
    )
    args = parser.parse_args()
    if os.getenv("OPERATIONAL_DEMO_ENABLED", "false").lower() != "true":
        raise SystemExit("Set OPERATIONAL_DEMO_ENABLED=true only in development/test.")
    subjects = json.loads(args.identity_map) if args.identity_map else None
    if subjects and (set(subjects) - set(ROLES) or len(set(subjects.values())) != len(subjects)):
        raise SystemExit("Map supported demo roles to distinct existing OAuth identities.")
    namespace = f"{args.namespace}-{uuid4().hex[:8]}" if args.reset else args.namespace
    if len(namespace) > 40 or not namespace.replace("-", "").isalnum():
        raise SystemExit("Namespace must be 1-40 alphanumeric characters or hyphens.")
    migrate(engine)
    with SessionLocal() as db:
        fixtures = seed_demo(db, subjects, namespace)
        existing = db.scalar(
            select(Consignment.id).where(Consignment.trade_id == fixtures["trade_id"])
        )
    if args.scenario != "ready":
        if existing:
            raise SystemExit(
                "This namespace already has operations. Use --reset to preserve it and start fresh."
            )
        result = Demo(SessionLocal, fixtures).scenario(args.scenario)
        fixtures["consignments"] = [c["id"] for c in result["consignments"]]
        fixtures["summary"] = {
            "availability": result["availability"],
            "settlement": {
                key: result["settlement"][key]
                for key in (
                    "net_allocated_minor",
                    "overapplied_minor",
                    "provider_verification",
                    "final_invoice_reconciliation",
                )
            },
            "dispatch_readiness": result["dispatch_readiness"],
        }
    print(json.dumps(fixtures, indent=2))


if __name__ == "__main__":
    main()
