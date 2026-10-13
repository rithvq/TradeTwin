"""Permission-filtered projections consumed by the existing eight-module workspace."""

from decimal import Decimal

from sqlalchemy import select

from app.trades.models import Item, Revision
from app.trades.terms import digest

from .access import has
from .ledger import view
from .models import (
    Assignment,
    Attachment,
    Closure,
    Consignment,
    Dispute,
    Event,
    Receipt,
    Vehicle,
)
from .quantities import availability, items, summary


def consignment_view(db, ctx, trade, row):
    from app.trades.access import participant_role

    side = participant_role(db, trade.id, ctx.org_id)
    actions = []
    for permission in (
        "consignment.plan",
        "consignment.cancel",
        "transport.assign",
        "assignment.respond",
        "shipment.event.record",
        "receipt.record",
        "receipt.correct",
        "receipt.close",
        "receipt.reopen",
        "goods.accept",
        "goods.acceptance.reverse",
        "dispute.open",
        "attachment.upload",
    ):
        if has(db, ctx, permission, trade.id, side):
            if not side and permission == "shipment.event.record":
                assignment = (
                    db.get(Assignment, row.active_assignment_id)
                    if row.active_assignment_id
                    else None
                )
                if not assignment or assignment.driver_user_id != ctx.user.id:
                    continue
            actions.append(permission)
    all_assignments = list(
        db.scalars(
            select(Assignment)
            .where(Assignment.consignment_id == row.id)
            .order_by(Assignment.created_at, Assignment.id)
        )
    )
    assignments = (
        all_assignments
        if side
        else [a for a in all_assignments if a.carrier_organization_id == ctx.org_id]
    )
    result = {
        **view(row, trade, ctx),
        "items": [view(i, trade) for i in items(db, row.id)],
        "assignments": [view(a, trade) for a in assignments],
        "dispatch_readiness": "NOT_ASSESSED",
        "allowed_actions": actions,
        "events": [
            view(e, trade)
            for e in db.scalars(
                select(Event)
                .where(Event.consignment_id == row.id)
                .order_by(Event.occurred_at, Event.created_at, Event.id)
            )
        ],
    }
    from app.trades.context_locks import phase4_installed
    from app.trades.errors import TradeError

    if phase4_installed(db) and has(db, ctx, "compliance.read", trade.id, side):
        from app.compliance.handoff import readiness

        try:
            action = (
                "DEPARTED"
                if row.movement_status in {"PICKED_UP", "IN_TRANSIT", "ARRIVED", "DELIVERY_CLOSED"}
                else "PICKUP_CONFIRMED"
            )
            result["dispatch_readiness"] = readiness(db, ctx, row.id, action)["state"]
        except TradeError:
            result["dispatch_readiness"] = "NOT_AVAILABLE"

    from .attachments import access

    documents = []
    for attachment in db.scalars(select(Attachment).where(Attachment.consignment_id == row.id)):
        try:
            access(db, ctx, attachment)
            documents.append(view(attachment, trade))
        except TradeError:
            continue
    result["documents"] = documents
    if side:
        from .receiving import receipt_view

        result.update(
            receipt_summary=summary(db, row),
            receipts=[
                receipt_view(db, ctx, trade, r)
                for r in db.scalars(
                    select(Receipt)
                    .where(Receipt.consignment_id == row.id)
                    .order_by(Receipt.created_at, Receipt.id)
                )
            ],
            closures=[
                view(c, trade)
                for c in db.scalars(
                    select(Closure)
                    .where(Closure.consignment_id == row.id)
                    .order_by(Closure.created_at, Closure.id)
                )
            ],
        )
    return result


def planning_context(db, ctx, trade, row):
    source = db.get(Revision, row.source_accepted_revision_id).facts_json
    goods = [
        {
            "line_ref": i.line_ref,
            "description": i.description_snapshot,
            "specification": i.specification_snapshot,
            "allocated_quantity": str(i.allocated_quantity),
            "uqc": i.uqc,
            "cargo_constraints": i.cargo_declarations_snapshot,
            "declared_hsn": db.get(Item, i.source_trade_item_revision_id).hsn_code,
        }
        for i in items(db, row.id)
    ]
    delivery = source["delivery_requirements"]
    inputs = {
        "schema_version": 1,
        "trade_id": trade.id,
        "consignment_id": row.id,
        "execution_mode": trade.execution_mode,
        "accepted_revision_id": trade.accepted_revision_id,
        "source_accepted_revision_id": row.source_accepted_revision_id,
        "consignment_row_version": row.row_version,
        "revision_alignment": row.revision_alignment,
        "origin_address": row.pickup_address_snapshot,
        "destination_address": row.delivery_address_snapshot,
        "origin_coordinates": None,
        "destination_coordinates": None,
        "pickup_window": {
            "start": row.plan_json["planned_pickup_start"],
            "end": row.plan_json["planned_pickup_end"],
        },
        "delivery_deadline": row.plan_json["expected_delivery_at"],
        "goods_lines": goods,
        "gross_weight_kg": row.plan_json["declared_gross_weight_kg"],
        "volume_m3": row.plan_json.get("declared_volume_m3"),
        "package_count": row.plan_json["package_count"],
        "commercial_freight_responsibility": source["commercial_terms"]["freight_payer"],
        "consolidation_allowed": delivery["consolidation_allowed"],
        "return_truck_allowed": delivery["return_truck_allowed"],
        "maximum_transshipments": delivery["maximum_transshipments"],
        "assignment_reference": row.active_assignment_id,
        "movement_purpose": source["movement_purpose"],
        "dispatch_readiness": "NOT_ASSESSED",
    }
    from app.document_desk.views import context_view

    documents = context_view(db, ctx, row.id)
    inputs.update(
        document_context_schema_version=1,
        document_context_hash=documents["document_context_hash"],
        document_evidence_refs=documents["linked_document_refs"],
        document_context_freshness=documents["freshness"],
    )
    from .access import has

    if has(db, ctx, "compliance.read", trade.id):
        from app.compliance.handoff import constraints

        inputs["compliance_constraints"] = constraints(
            db,
            ctx,
            row.id,
            "DEPARTED" if row.movement_status == "PICKED_UP" else "PICKUP_CONFIRMED",
        )
    return {**inputs, "input_hash": digest(inputs), "request_id": ctx.request_id}


def exceptions(db, trade, consignments):
    result = []
    for row in consignments:

        def add(kind, source_id, declaration="REPORTED", consignment_id=row.id):
            result.append(
                {
                    "type": kind,
                    "consignment_id": consignment_id,
                    "source_id": source_id,
                    "fact_status": declaration,
                    "verification_status": "NOT_ASSESSED",
                    "execution_mode": trade.execution_mode,
                }
            )

        if row.revision_alignment != "CURRENT":
            add("REVISION_REVIEW_REQUIRED", row.id, "DECLARED")
        if row.plan_json.get("declared_volume_m3") is None:
            add("CAPACITY_INFORMATION_MISSING", row.id, "DECLARED")
        for proposal in db.scalars(
            select(Assignment).where(
                Assignment.consignment_id == row.id,
                Assignment.status == "PROPOSED",
                Assignment.vehicle_id.is_not(None),
            )
        ):
            vehicle = db.get(Vehicle, proposal.vehicle_id)
            if Decimal(row.plan_json["declared_gross_weight_kg"]) > Decimal(
                vehicle.vehicle_json["declared_payload_capacity_kg"]
            ):
                add("DECLARED_CAPACITY_EXCEEDED", proposal.id, "DECLARED")
        for line in summary(db, row):
            if Decimal(line["short_quantity"]) > 0:
                add("SHORTAGE_RECORDED", row.current_delivery_closure_id)
            if Decimal(line["rejected_quantity"]) > 0:
                add("GOODS_REJECTED", line["consignment_item_id"])
        for ev in db.scalars(
            select(Event).where(
                Event.consignment_id == row.id, Event.event_type == "INCIDENT_REPORTED"
            )
        ):
            add(ev.payload_json["incident_type"] + "_REPORTED", ev.id)
    return result


def workspace(db, ctx, trade):
    from app.trades.access import participant_role

    from .disputes import dispute_view
    from .payments import settlement

    side = participant_role(db, trade.id, ctx.org_id)
    consignments = list(
        db.scalars(
            select(Consignment)
            .where(Consignment.trade_id == trade.id)
            .order_by(Consignment.created_at, Consignment.id)
        )
    )
    financial = any(
        has(db, ctx, p, trade.id, side)
        for p in (
            "payment_schedule.propose",
            "payment_schedule.approve",
            "payment.report",
            "payment.acknowledge",
        )
    )
    money = settlement(db, ctx, trade) if financial else None
    risk = exceptions(db, trade, consignments)
    if money:
        if int(money["overapplied_minor"]) > 0:
            risk.append(
                {
                    "type": "PAYMENT_OVERAPPLICATION",
                    "source_id": trade.active_payment_schedule_id,
                    "fact_status": "REPORTED",
                    "verification_status": "NOT_ASSESSED",
                    "execution_mode": trade.execution_mode,
                }
            )
        risk.extend(
            {
                "type": "PAYMENT_DISPUTED",
                "source_id": p["id"],
                "fact_status": "REPORTED",
                "verification_status": "NOT_ASSESSED",
                "execution_mode": trade.execution_mode,
            }
            for p in money["payments"]
            if p["status"] == "DISPUTED"
        )
    attachments = []
    from app.trades.errors import TradeError

    from .attachments import access

    for a in db.scalars(select(Attachment).where(Attachment.trade_id == trade.id)):
        try:
            access(db, ctx, a)
            attachments.append(view(a, trade))
        except TradeError:
            pass
    result = {
        "trade_id": trade.id,
        "execution_mode": trade.execution_mode,
        "agreement_status": trade.agreement_status,
        "accepted_revision_id": trade.accepted_revision_id,
        "etag": f'"{trade.row_version}"',
        "row_version": trade.row_version,
        "request_id": ctx.request_id,
        "availability": availability(db, trade) if trade.accepted_revision_id else [],
        "consignments": [consignment_view(db, ctx, trade, c) for c in consignments],
        "disputes": [
            dispute_view(db, ctx, trade, d)
            for d in db.scalars(select(Dispute).where(Dispute.trade_id == trade.id))
        ],
        "settlement": money,
        "exceptions": risk,
        "documents": attachments,
        "dispatch_readiness": "NOT_ASSESSED",
        "allowed_actions": [
            p
            for p in ("consignment.plan", "dispute.open", "attachment.upload")
            if has(db, ctx, p, trade.id, side)
        ],
    }
    nodes = (
        [
            {"id": trade.id, "type": "Trade", "label": trade.reference},
            {"id": trade.accepted_revision_id, "type": "Revision", "label": "Accepted agreement"},
        ]
        if trade.accepted_revision_id
        else [{"id": trade.id, "type": "Trade", "label": trade.reference}]
    )
    edges = (
        [{"source": trade.id, "target": trade.accepted_revision_id, "type": "ACCEPTED_REVISION"}]
        if trade.accepted_revision_id
        else []
    )

    def relate(parent, row, kind, label):
        if row["id"] not in {n["id"] for n in nodes}:
            nodes.append({"id": row["id"], "type": kind, "label": label})
        edges.append({"source": parent, "target": row["id"], "type": kind})

    for c in result["consignments"]:
        relate(c["source_accepted_revision_id"], c, "Consignment", c["reference"])
        if c["source_accepted_revision_id"] not in {n["id"] for n in nodes}:
            nodes.append(
                {
                    "id": c["source_accepted_revision_id"],
                    "type": "Revision",
                    "label": "Source agreement",
                }
            )
            edges.append(
                {
                    "source": trade.id,
                    "target": c["source_accepted_revision_id"],
                    "type": "SOURCE_REVISION",
                }
            )
        for assignment in c["assignments"]:
            relate(c["id"], assignment, "Assignment", assignment["status"])
            for resource in ("vehicle_id", "driver_user_id"):
                if assignment[resource]:
                    relate(
                        assignment["id"],
                        {"id": assignment[resource]},
                        resource,
                        (assignment["vehicle_snapshot"] or {}).get("registration_number", "Driver")
                        if resource == "vehicle_id"
                        else (assignment["driver_snapshot"] or {}).get("display_name", "Driver"),
                    )
        for ev in c["events"]:
            relate(c["id"], ev, "Event", ev["event_type"])
        for receipt in c["receipts"]:
            relate(
                c["id"],
                receipt,
                "Receipt",
                "Effective receipt" if receipt["effective"] else "Superseded receipt",
            )
            for line in receipt["lines"]:
                relate(
                    receipt["id"],
                    line,
                    "ReceiptLine",
                    line["delivered_quantity"] + " " + line["uqc"],
                )
                for decision in line["decisions"]:
                    relate(line["id"], decision, "Inspection", decision["entry_type"])
    for dispute in result["disputes"]:
        relate(dispute["consignment_id"] or trade.id, dispute, "Dispute", dispute["status"])
    if money:
        for s in money["schedules"]:
            relate(trade.id, s, "Schedule", s["status"])
            for line in s["lines"]:
                relate(s["id"], {"id": line["obligation_ref"]}, "Obligation", line["label"])
        for p in money["payments"]:
            relate(trade.id, p, "Payment", p["status"])
            for a in p["allocations"]:
                relate(p["id"], a, "Allocation", a["entry_type"])
                edges.append(
                    {"source": a["id"], "target": a["obligation_ref"], "type": "FUNDS_OBLIGATION"}
                )
    result["graph"] = {"nodes": nodes, "edges": edges, "execution_mode": trade.execution_mode}
    return result
