"""Current permission-filtered journey, without a global completed flag or cash total."""

from decimal import Decimal

from sqlalchemy import select

from app.compliance import context, handoff
from app.compliance.clock import aware, instant
from app.corridor.models import DriverResponse, MotionHead, RecoveryCase
from app.corridor.projection import dependency, plan
from app.document_desk import access as document_access
from app.document_desk.models import Assessment as DocumentAssessment
from app.document_desk.models import Document, Finding
from app.freight.access import price_access
from app.freight.models import Commitment, SelectionHead
from app.operations.access import has
from app.operations.models import Assignment, Dispute, Event
from app.operations.payments import settlement
from app.operations.quantities import availability, q, summary
from app.trades.errors import TradeError
from app.trades.models import Approval, Revision
from app.trades.terms import digest

from . import access, tasks
from .models import Projection

MODULE_PERMISSIONS = {
    "SHIPMENTS": {"trade.read", "consignment.read"},
    "DOCUMENTS": {"document.read"},
    "COMPLIANCE": {"compliance.read"},
    "GRAPH": {"consignment.read", "tradetwin.read"},
    "RISK": {"consignment.read"},
    "OPTIMIZER": {"tradetwin.read", "freight.rfq.invited.read"},
    "REGULATIONS": {"regulation.read", "readiness.read"},
    "EVIDENCE": {"evidence.read", "evidence.replay.request"},
}


def read(db, ctx, ident, role=None, module=None, consignment_id=None):
    trade, side, consignments = access.workspace(db, ctx, ident)
    at = instant(db)
    permissions = access.capabilities(db, ctx, trade.id)
    revision = db.get(Revision, trade.accepted_revision_id) if trade.accepted_revision_id else None
    result = {
        "schema_version": 1,
        "schema_code": "TRADE_WORKSPACE_V1",
        "trade_id": trade.id,
        "trade_reference": trade.reference,
        "execution_mode": trade.execution_mode,
        "current_accepted_revision_id": trade.accepted_revision_id,
        "accepted_terms_hash": revision.terms_hash if revision else None,
        "computed_at": at.isoformat(),
        "source_context_version": context.version(db, trade.id),
        "projection_version": 1,
        "projection_freshness": "CURRENT",
        "temporal_valid_until": None,
        "permitted_module_codes": [
            m for m, codes in MODULE_PERMISSIONS.items() if set(permissions) & codes
        ],
        "selected_workspace_role": role,
        "commercial": {
            "agreement_status": trade.agreement_status,
            "current_revision_id": trade.current_revision_id if side else None,
            "accepted_revision_id": trade.accepted_revision_id,
            "pending_amendment_id": trade.pending_amendment_id if side else None,
            "active_offer_id": trade.active_offer_id if side else None,
        },
        "consignments": [],
        "permitted_action_codes": permissions,
        "source_refs": [],
        "limitations": [
            "Receipt, inspection, goods acknowledgment, freight and tax are independent.",
            "Reported location and motion are not independently verified.",
            "Recovery execution and full pilot qualification await missing verified capabilities.",
        ],
    }
    watermarks = {
        "accepted_revision_id": trade.accepted_revision_id,
        "trade_row_version": trade.row_version,
        "visible_consignments": [],
        "visible_documents": [],
    }
    boundaries = []
    for cn in consignments:
        assignment = (
            db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
        )
        route = plan(db, cn)
        motion = db.get(MotionHead, cn.id)
        response = (
            db.get(DriverResponse, motion.latest_response_id)
            if motion and motion.latest_response_id
            else None
        )
        recovery = db.scalar(
            select(RecoveryCase)
            .where(
                RecoveryCase.consignment_id == cn.id,
                RecoveryCase.status.not_in(["RESOLVED", "CLOSED_NO_CHANGE"]),
            )
            .order_by(RecoveryCase.created_at.desc(), RecoveryCase.id.desc())
        )
        corridor = dependency(db, trade, cn)
        if corridor and corridor["valid_until"]:
            boundaries.append(corridor["valid_until"])
        entry = {
            "consignment_id": cn.id,
            "consignment_reference": cn.reference,
            "planning_status": cn.planning_status,
            "movement_status": cn.movement_status,
            "revision_alignment": cn.revision_alignment,
            "current_assignment_id": cn.active_assignment_id,
            "assignment_status": assignment.status if assignment else "NOT_ASSIGNED",
            "assignment_basis": {
                "id": assignment.id,
                "version": assignment.row_version,
                "status": assignment.status,
            }
            if assignment
            else None,
            "current_route_plan_revision_id": route.id if route else None,
            "current_effective_freight_amendment_id": None,
            "pickup_readiness": gate(db, ctx, cn, "PICKUP_CONFIRMED"),
            "departure_readiness": gate(db, ctx, cn, "DEPARTED"),
            "recovery_resume_readiness": {
                "state": "UNSUPPORTED",
                "reasons": ["EXECUTABLE_RECOVERY_NOT_IMPLEMENTED"],
            }
            if recovery
            else None,
            "reported_motion": motion.motion if motion else "UNKNOWN",
            "reported_motion_observed_at": aware(response.observed_at).isoformat()
            if response
            else None,
            "recovery_case_id": recovery.id if recovery else None,
            "application_protection_state": recovery.protection_state if recovery else None,
            "corridor_projection_hash": corridor["projection_hash"] if corridor else None,
            "estimated_arrival_at": route.route_plan_json["estimated_arrival_at"]
            if route
            else cn.plan_json.get("expected_delivery_at"),
            "estimated_arrival_basis": "COMMITTED_ROUTE_ESTIMATE"
            if route
            else "DECLARED_PLAN_ESTIMATE",
            "estimated_arrival_as_of": aware(route.created_at).isoformat() if route else None,
            "historical_authorisation_coverage": coverage(db, cn),
            "current_action_blocker_refs": [],
            "receipt_lines": line_quantities(db, cn) if side else [],
        }
        if has(db, ctx, "compliance.read", trade.id):
            for key in ["pickup_readiness", "departure_readiness"]:
                for reason in entry[key]["reasons"]:
                    entry["current_action_blocker_refs"].append(
                        {"consignment_id": cn.id, "action": entry[key]["action"], "code": reason}
                    )
        result["consignments"].append(entry)
        watermarks["visible_consignments"].append(
            {
                "id": cn.id,
                "version": cn.row_version,
                "route_id": route.id if route else None,
                "route_hash": route.content_hash if route else None,
                "motion_epoch": motion.stationary_epoch if motion else 0,
                "corridor": corridor,
            }
        )
    result["fulfilment"] = fulfilment(db, ctx, trade, consignments, side)
    result["documents"] = documents(db, ctx, trade, watermarks)
    if side and revision and access.affordable_view(db, ctx, trade):
        finance = settlement(db, ctx, trade)
        result["goods_finance"] = {
            "authoritative_obligation_schedule_id": finance["active_schedule_id"],
            "obligation_total_minor": finance["scheduled_goods_minor"]
            if finance["active_schedule_id"]
            else None,
            "net_acknowledged_allocated_minor": finance["net_allocated_minor"],
            "unallocated_acknowledged_minor": finance["unallocated_acknowledged_minor"],
            "pending_reported_minor": str(
                sum(
                    int(p["amount_minor"]) for p in finance["payments"] if p["status"] == "REPORTED"
                )
            ),
            "remaining_unfunded_obligation_minor": finance["outstanding_scheduled_minor"]
            if finance["active_schedule_id"]
            else None,
            "ledger_basis": "MANUAL_COUNTERPARTY_ACKNOWLEDGMENT",
            "bank_settlement_assessed": False,
            "tax_payment_assessed": False,
        }
        watermarks["finance"] = result["goods_finance"]
    if side and revision and visible_price(db, ctx, trade):
        result["freight"] = []
        for cn in consignments:
            head = db.scalar(select(SelectionHead).where(SelectionHead.consignment_id == cn.id))
            if not head or not head.current_commitment_id:
                continue
            committed = db.get(Commitment, head.current_commitment_id)
            price = committed.commitment_json["price_snapshot"]
            result["freight"].append(
                {
                    "consignment_id": cn.id,
                    "current_commitment_id": committed.id,
                    "current_effective_contract_hash": committed.content_hash,
                    "current_effective_amendment_id": None,
                    "accepted_carrier_payable_minor": price.get("carrier_payable_total_minor"),
                    "comparison_estimate_minor": committed.commitment_json.get(
                        "comparison_cost_snapshot", {}
                    ).get("comparison_total_minor"),
                    "comparison_estimate_as_of": aware(committed.created_at).isoformat(),
                    "carrier_payment_assessed": False,
                }
            )
    result["commercial"]["current_party_approval_summary"] = (
        [
            {"side": approval.participant_role, "decision": approval.decision}
            for approval in db.scalars(
                select(Approval).where(
                    Approval.trade_id == trade.id, Approval.offer_id == trade.active_offer_id
                )
            )
        ]
        if side and trade.active_offer_id
        else []
    )
    result["risk"] = {
        "current_action_blockers": [
            b for cn in result["consignments"] for b in cn["current_action_blocker_refs"]
        ],
        "applicable_operational_alerts": [
            {
                "consignment_id": cn["consignment_id"],
                "protection": cn["application_protection_state"],
            }
            for cn in result["consignments"]
            if cn["application_protection_state"]
        ],
        "coverage_limitations": [
            "Corridor feed coverage is not comprehensive.",
            "Government authenticity, freight payment and tax settlement are not inferred.",
        ],
    }
    result["source_watermarks"] = watermarks
    result["source_manifest_hash"] = digest(watermarks)
    result["source_refs"] = (
        [{"subject_type": "TRADE_REVISION", "subject_id": trade.accepted_revision_id}]
        if revision
        else []
    )
    result["temporal_valid_until"] = min(boundaries) if boundaries else None
    result["tasks"] = tasks.derive(db, ctx, trade, side, result)
    if consignment_id:
        result["consignments"] = [
            cn for cn in result["consignments"] if cn["consignment_id"] == consignment_id
        ]
        result["tasks"] = [
            t for t in result["tasks"] if t["consignment_id"] in {None, consignment_id}
        ]
    if module:
        result["tasks"] = [t for t in result["tasks"] if t["module_code"] == module]
    return result


def gate(db, ctx, cn, action):
    if not has(db, ctx, "compliance.read", cn.trade_id):
        return {"action": action, "state": "NOT_AVAILABLE", "reasons": []}
    try:
        value = handoff.readiness(db, ctx, cn.id, action)
        token = value["authorisation"]
        return {
            "action": action,
            "state": value["state"],
            "reasons": [
                r if isinstance(r, str) else r.get("requirement_code", "REVIEW_REQUIRED")
                for r in value["reasons"]
            ],
            "authorisation_id": token["id"] if token else None,
            "expires_at": token["expires_at"] if token else None,
        }
    except TradeError as exc:
        return {"action": action, "state": "BLOCKED", "reasons": [exc.code]}


def coverage(db, cn):
    from app.compliance.models import Authorization

    if cn.movement_status == "NOT_STARTED":
        return "NOT_APPLICABLE"
    if cn.phase4_legacy_movement:
        return "NOT_RECORDED"
    movement = list(
        db.scalars(
            select(Event).where(
                Event.consignment_id == cn.id,
                Event.event_type.in_(["PICKUP_CONFIRMED", "DEPARTED"]),
            )
        )
    )
    covered = set(
        db.scalars(
            select(Authorization.consumed_event_id).where(
                Authorization.consignment_id == cn.id, Authorization.consumed_event_id.is_not(None)
            )
        )
    )
    return "RECORDED" if movement and all(e.id in covered for e in movement) else "NOT_RECORDED"


def visible_price(db, ctx, trade):
    try:
        return price_access(db, ctx, trade)
    except TradeError as exc:
        if exc.code != "FREIGHT_PAYER_UNRESOLVED":
            raise
        return False


def line_quantities(db, cn):
    return [
        {
            "trade_line_ref": row["line_ref"],
            "uqc": row["uqc"],
            "allocated_quantity": row["allocated_quantity"],
            "dispatched_quantity": row["loaded_quantity"] or "0.000000",
            "current_net_received_quantity": row["received_quantity"],
            "inspection_accepted_quantity": row["accepted_quantity"],
            "inspection_rejected_quantity": row["rejected_quantity"],
            "inspection_pending_quantity": row["pending_inspection_quantity"],
            "final_short_quantity": row["short_quantity"],
        }
        for row in summary(db, cn)
    ]


def fulfilment(db, ctx, trade, consignments, side):
    if not side or not trade.accepted_revision_id:
        return {
            "ordered_lines": [],
            "open_delivery_closure_count": None,
            "open_dispute_count": None,
        }
    lines = []
    for line in availability(db, trade):
        entry = {
            "trade_line_ref": line["line_ref"],
            "description": line["description"],
            "ordered_quantity": line["ordered_quantity"],
            "uqc": line["uqc"],
        }
        matches = [
            item
            for cn in consignments
            if cn.planning_status != "CANCELLED"
            for item in line_quantities(db, cn)
            if item["trade_line_ref"] == line["line_ref"] and item["uqc"] == line["uqc"]
        ]
        for key in [
            "allocated_quantity",
            "dispatched_quantity",
            "current_net_received_quantity",
            "inspection_accepted_quantity",
            "inspection_rejected_quantity",
            "inspection_pending_quantity",
            "final_short_quantity",
        ]:
            entry[key] = q(sum((Decimal(row[key]) for row in matches), Decimal(0)))
        lines.append(entry)
    return {
        "ordered_lines": lines,
        "open_delivery_closure_count": sum(
            c.movement_status == "ARRIVED" and not c.current_delivery_closure_id
            for c in consignments
        ),
        "open_dispute_count": len(
            list(
                db.scalars(
                    select(Dispute.id).where(
                        Dispute.trade_id == trade.id,
                        Dispute.status.not_in(["CLOSED", "RESOLVED", "WITHDRAWN"]),
                    )
                )
            )
        ),
    }


def documents(db, ctx, trade, watermarks):
    records, findings = [], 0
    for doc in db.scalars(
        select(Document).where(Document.trade_id == trade.id).order_by(Document.id)
    ):
        try:
            document_access.document(db, ctx, doc.id)
        except TradeError:
            continue
        review_required = doc.lifecycle_status == "ACTIVE" and not doc.effective_fact_revision_id
        records.append(
            {
                "id": doc.id,
                "document_type": doc.document_type,
                "current_version_id": doc.current_version_id,
                "reviewed_fact_revision_id": doc.effective_fact_revision_id,
                "review_required": review_required,
                "lifecycle_status": doc.lifecycle_status,
            }
        )
        watermarks["visible_documents"].append(
            {
                "id": doc.id,
                "version": doc.row_version,
                "current": doc.current_version_id,
                "reviewed": doc.effective_fact_revision_id,
            }
        )
        if doc.current_version_id:
            latest = db.scalar(
                select(DocumentAssessment)
                .where(DocumentAssessment.document_version_id == doc.current_version_id)
                .order_by(DocumentAssessment.created_at.desc(), DocumentAssessment.id.desc())
            )
            if latest:
                findings += len(
                    list(
                        db.scalars(
                            select(Finding.id).where(
                                Finding.assessment_run_id == latest.id,
                                Finding.outcome.in_(["FAIL", "UNKNOWN", "CONFLICT"]),
                            )
                        )
                    )
                )
    return {
        "required_evidence_summary": [],
        "visible_unresolved_review_count": sum(r["review_required"] for r in records),
        "visible_discrepancy_count": findings,
        "authority_observation_limitations": [
            "Extraction, review, signatures and provider observations are separate dimensions."
        ],
        "evidence_currency_summary": "VISIBLE_CURRENT_HEADS_ONLY",
        "visible_records": records,
    }


def refresh_head(db, trade):
    value = {
        "trade_id": trade.id,
        "agreement_status": trade.agreement_status,
        "accepted_revision_id": trade.accepted_revision_id,
        "context_version": context.version(db, trade.id),
    }
    fingerprint = digest(value)
    row = db.get(Projection, trade.id)
    if not row:
        row = Projection(
            trade_id=trade.id,
            source_context_version=value["context_version"],
            source_manifest_hash=fingerprint,
            source_watermarks_json=value,
            operational_projection_json=value,
            computed_at=instant(db),
        )
        db.add(row)
    elif row.source_manifest_hash != fingerprint:
        row.source_context_version = value["context_version"]
        row.source_manifest_hash = fingerprint
        row.source_watermarks_json = value
        row.operational_projection_json = value
        row.projection_version += 1
        row.row_version += 1
        row.computed_at = instant(db)
    return row
