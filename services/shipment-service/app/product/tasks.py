"""Tasks are projections of authoritative records. There is no complete-task command."""

from datetime import timedelta
from decimal import Decimal

from app.compliance.clock import aware, instant
from app.operations.access import fail, has
from app.trades.terms import digest

from .models import TaskState

TARGETS = {
    "AGREEMENT_ACCEPT": "/trades/{trade}",
    "ASSIGNMENT_CONFIRM": "/shipments/consignments/{cn}/assignment",
    "DOCUMENT_REVIEW": "/documents/trades/{trade}",
    "COMPLIANCE_RELEASE": "/shipments/trades/{trade}/operations?module=Compliance",
    "FREIGHT_DECISION": "/shipments/trades/{trade}/operations?module=Optimizer",
    "CORRIDOR_REVIEW": "/shipments/trades/{trade}/operations?module=Risk",
    "INSPECTION": "/shipments/consignments/{cn}/inspection",
    "PAYMENT_ACK": "/shipments/trades/{trade}/payments",
}


def derive(db, ctx, trade, side, workspace):
    result = []

    def add(
        code,
        module,
        subject,
        kind,
        basis,
        permission,
        title,
        explanation,
        cn=None,
        blocker=False,
        due=None,
        role="AUTHORISED_REVIEWER",
    ):
        key = digest({"trade": trade.id, "subject": subject, "code": code})
        fingerprint = digest(basis)
        state = db.get(TaskState, (trade.id, ctx.user.id, key, fingerprint))
        actionable = has(db, ctx, permission, trade.id)
        result.append(
            {
                "task_key": key,
                "task_code": code,
                "trade_id": trade.id,
                "consignment_id": cn,
                "module_code": module,
                "authoritative_subject_type": kind,
                "authoritative_subject_id": subject,
                "basis_hash": fingerprint,
                "status": "BLOCKED"
                if blocker
                else "OPEN"
                if actionable
                else "WAITING_ON_OTHER_PARTY",
                "priority": "BLOCKER" if blocker else "ACTION_REQUIRED",
                "title": title,
                "explanation": explanation
                if actionable
                else explanation + " Waiting for an authorised reviewer.",
                "required_permission_codes": [permission],
                "responsible_organisation_id": ctx.org_id if actionable else None,
                "responsible_role_code": role,
                "due_at": due,
                "deadline_basis": "DOCUMENT_VALIDITY" if due else "NONE",
                "deadline_source_ref": None,
                "dependency_task_keys": [],
                "actionable_by_current_user": actionable,
                "action_code": code if actionable else None,
                "internal_screen_target": TARGETS[code].format(trade=trade.id, cn=cn),
                "expected_context_version": workspace["source_context_version"],
                "expected_resource_hash": fingerprint,
                "source_refs": [{"subject_type": kind, "subject_id": subject}],
                "created_from_revision_reference": trade.accepted_revision_id,
                "user_seen_at": aware(state.seen_at).isoformat()
                if state and state.seen_at
                else None,
                "user_state_etag": f'"{state.row_version}"' if state else None,
                "user_snoozed_until": aware(state.snoozed_until).isoformat()
                if state
                and state.snoozed_until
                and state.task_basis_hash == fingerprint
                and not blocker
                else None,
            }
        )

    if side and trade.active_offer_id:
        add(
            "AGREEMENT_ACCEPT",
            "SHIPMENTS",
            trade.active_offer_id,
            "OFFER",
            {
                "offer": trade.active_offer_id,
                "revision": trade.current_revision_id,
                "version": trade.row_version,
            },
            f"order.confirm.{side.lower()}",
            "Review exact agreement",
            "Accept or reject the offered revision through commercial review.",
        )
    for cn in workspace["consignments"]:
        ident = cn["consignment_id"]
        if cn["assignment_status"] == "PROPOSED":
            add(
                "ASSIGNMENT_CONFIRM",
                "SHIPMENTS",
                cn["current_assignment_id"],
                "ASSIGNMENT",
                cn["assignment_basis"],
                "assignment.respond",
                "Confirm transport assignment",
                "Carrier confirmation is required before movement.",
                ident,
            )
        if (
            cn["movement_status"] in {"NOT_STARTED", "PICKED_UP"}
            and cn["planning_status"] != "CANCELLED"
        ):
            action = (
                "pickup_readiness"
                if cn["movement_status"] == "NOT_STARTED"
                else "departure_readiness"
            )
            readiness = cn[action]
            if readiness["state"] != "READY":
                add(
                    "COMPLIANCE_RELEASE",
                    "COMPLIANCE",
                    ident,
                    "CONSIGNMENT",
                    {"context": workspace["source_context_version"], "readiness": readiness},
                    "compliance.evaluate",
                    "Resolve movement evidence",
                    "Fresh facts, evidence, review, packet and driver acknowledgment required.",
                    ident,
                    True,
                )
        if cn["application_protection_state"] in {
            "PREPARATION_BLOCKED",
            "MOVEMENT_ACTION_BLOCKED",
            "RELEASE_PENDING",
        }:
            add(
                "CORRIDOR_REVIEW",
                "RISK",
                cn["recovery_case_id"] or ident,
                "RECOVERY_CASE",
                {
                    "case": cn["recovery_case_id"],
                    "protection": cn["application_protection_state"],
                    "corridor": cn["corridor_projection_hash"],
                },
                "tradetwin.plan.apply",
                "Review corridor protection",
                "Operational protection is not proof that the vehicle has stopped.",
                ident,
                True,
            )
        if side and any(
            Decimal(line["inspection_pending_quantity"]) > 0 for line in cn.get("receipt_lines", [])
        ):
            add(
                "INSPECTION",
                "SHIPMENTS",
                ident,
                "CONSIGNMENT",
                cn["receipt_lines"],
                "goods.accept",
                "Inspect received goods",
                "Receipt is not inspection acceptance.",
                ident,
                role="BUYER_RECEIVER",
            )
    for document in workspace["documents"].get("visible_records", []):
        if document["review_required"]:
            add(
                "DOCUMENT_REVIEW",
                "DOCUMENTS",
                document["id"],
                "DOCUMENT",
                document,
                "document.review",
                "Review source transcription",
                "Extraction is proposed until review; corrections do not change accepted terms.",
            )
    finance = workspace.get("goods_finance")
    if finance and int(finance["pending_reported_minor"]) > 0:
        add(
            "PAYMENT_ACK",
            "SHIPMENTS",
            trade.id,
            "TRADE",
            finance,
            "payment.acknowledge",
            "Review reported goods payment",
            "Seller acknowledgment remains distinct from bank settlement.",
            role="SELLER_FINANCE",
        )
    return sorted(
        result, key=lambda t: (t["priority"] != "BLOCKER", t["module_code"], t["task_key"])
    )


def change(db, ctx, ident, payload):
    from .workspace import read

    workspace = read(db, ctx, ident)
    task = next((t for t in workspace["tasks"] if t["task_key"] == payload.task_key), None)
    if not task or task["basis_hash"] != payload.task_basis_hash:
        fail("TASK_BASIS_STALE", "The task no longer has this authoritative basis.", status=412)
    if payload.operation == "SNOOZE" and task["priority"] == "BLOCKER":
        fail("TASK_ACTION_NOT_PERMITTED", "Critical blockers cannot be snoozed.", status=422)
    at = instant(db)
    if payload.operation == "SNOOZE" and (
        not payload.snoozed_until or not at < payload.snoozed_until <= at + timedelta(days=1)
    ):
        fail(
            "TASK_ACTION_NOT_PERMITTED", "Choose a future snooze time within 24 hours.", status=422
        )
    key = (ident, ctx.user.id, payload.task_key, payload.task_basis_hash)
    row = db.get(TaskState, key)
    if not row:
        row = TaskState(
            trade_id=ident,
            user_id=ctx.user.id,
            task_key=payload.task_key,
            task_basis_hash=payload.task_basis_hash,
            row_version=0,
        )
        db.add(row)
    elif ctx.if_match != f'"{row.row_version}"':
        fail("TASK_BASIS_STALE", "Task-user state changed; reload its ETag.", status=412)
    row.row_version += 1
    if payload.operation == "SEEN":
        row.seen_at = at
    else:
        row.snoozed_until = payload.snoozed_until if payload.operation == "SNOOZE" else None
        row.snooze_reason = payload.reason
    return {
        "task_key": row.task_key,
        "basis_hash": row.task_basis_hash,
        "etag": f'"{row.row_version}"',
        "business_action_completed": False,
    }
