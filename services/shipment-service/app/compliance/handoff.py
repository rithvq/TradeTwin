"""Permission-filtered evidence chain and immutable constraint handoff, not an optimizer."""

from sqlalchemy import select

from app.operations.access import exists
from app.trades.terms import digest

from . import context, dispatch, evaluations, governance, public_records
from .clock import instant
from .ledger import view
from .models import (
    Authorization,
    Binding,
    Evaluation,
    Packet,
    PacketAck,
    ReleaseReview,
    Requirement,
    Source,
)


def readiness(db, ctx, ident, action):
    trade, cn, _ = context.access(db, ctx, ident)
    head = context.heads(db, cn)
    evaluation_id = getattr(
        head,
        "current_pickup_evaluation_id"
        if action == "PICKUP_CONFIRMED"
        else "current_departure_evaluation_id",
        None,
    )
    authorization_id = getattr(
        head,
        "pickup_authorization_id" if action == "PICKUP_CONFIRMED" else "departure_authorization_id",
        None,
    )
    state, reasons = "NOT_ASSESSED", []
    evaluation = None
    if evaluation_id:
        evaluation = evaluations.read(db, ctx, evaluation_id)
        state = (
            "EVALUATING"
            if evaluation["job_state"] in {"QUEUED", "RUNNING"}
            else evaluation["decision"] or "BLOCKED"
        )
        if evaluation["freshness"] != "CURRENT":
            state, reasons = "BLOCKED", [evaluation["freshness"]]
        reasons += evaluation["blockers"]
    authorisation = None
    if authorization_id:
        authorisation = dispatch.read(db, ctx, authorization_id)
        if authorisation["effective_state"] == "ACTIVE":
            state = "READY"
        else:
            reasons.append(authorisation["effective_state"])
    return {
        "schema_version": "PH4_READINESS_V1",
        "consignment_id": cn.id,
        "action": action,
        "execution_mode": trade.execution_mode,
        "state": state,
        "reasons": reasons,
        "context_version": context.version(db, trade.id),
        "evaluation": evaluation,
        "authorisation": authorisation,
        "checked_at": instant(db).isoformat(),
        "label": "Platform dispatch authorisation",
        "historical_notice": "Historical movement; Phase 4 authorisation not recorded"
        if cn.phase4_legacy_movement
        else None,
        "operational_alerts": operational_alerts(db, trade, cn),
    }


def operational_alerts(db, trade, cn):
    """Current operational warnings never rewrite the decision that allowed departure."""
    if cn.movement_status not in {"IN_TRANSIT", "ARRIVED", "PARTIALLY_DELIVERED"}:
        return []
    head = context.heads(db, cn)
    row = (
        db.get(Evaluation, head.current_departure_evaluation_id)
        if head and (head.current_departure_evaluation_id)
        else None
    )
    if not row:
        return []
    from .observations import timestamp

    alerts = []
    at = instant(db)
    binding = db.get(Binding, row.binding_revision_id) if row.binding_revision_id else None
    if binding:
        from app.document_desk.models import VerificationCheck, VerificationResult

        from .dependencies import verification_state

        records, _ = verification_state(db, binding)
        previous = {r["id"] for r in row.snapshot_json.get("verification_results", [])}
        for observed in records:
            if observed["id"] in previous:
                continue
            result = db.get(VerificationResult, observed["id"])
            data = result.result_json
            if (
                data.get("normalised_result", {}).get("status")
                in {"CANCELLED", "EXPIRED", "INACTIVE", "REVOKED", "INVALID"}
                or data.get("signature_integrity") == "INVALID"
            ):
                check = db.get(VerificationCheck, result.verification_check_id)
                alerts.append(
                    {
                        "code": "ADVERSE_PROOF_AFTER_DISPATCH",
                        "severity": "HIGH",
                        "explanation": "New adverse " + check.check_type + " observation requires "
                        "investigation. The historical departure decision remains immutable.",
                    }
                )
        if any(
            context.source_state(db, d["reference"]["document_version_id"]).get("lifecycle_status")
            != "ACTIVE"
            for d in row.snapshot_json.get("documents", [])
        ):
            alerts.append(
                {
                    "code": "SOURCE_ARCHIVED_AFTER_DISPATCH",
                    "severity": "HIGH",
                    "explanation": "A source used for departure was archived. Investigate current "
                    "movement evidence without rewriting the historical authorisation.",
                }
            )
    for deadline in row.coverage_json.get("authority_deadlines", []):
        end = timestamp(deadline["timestamp"])
        if end and at >= end:
            alerts.append(
                {
                    "code": deadline["code"],
                    "severity": "HIGH",
                    "explanation": "A bound document expired after dispatch. "
                    "Obtain current evidence; historical authorisation is unchanged.",
                }
            )
    _, manifest, _ = governance.resolve(db, trade.execution_mode)
    if manifest != row.registry_manifest_json:
        alerts.append(
            {
                "code": "REGULATION_CHANGED_AFTER_DISPATCH",
                "severity": "HIGH",
                "explanation": "The effective registry changed. Review applicability "
                "for the ongoing movement; this is not retrospective clearance.",
            }
        )
    holds = db.scalars(
        select(context.Hold).where(context.Hold.trade_id == trade.id, context.Hold.active.is_(True))
    ).all()
    if any(h.consignment_id in {None, cn.id} for h in holds):
        alerts.append(
            {
                "code": "INTEGRITY_HOLD_AFTER_DISPATCH",
                "severity": "HIGH",
                "explanation": "An active integrity hold requires investigation.",
            }
        )
    return alerts


def evidence(db, ctx, ident, authorization=False):
    token = exists(db, Authorization, ident) if authorization else None
    evaluation = exists(db, Evaluation, token.evaluation_id if token else ident)
    trade, cn, side = context.access(db, ctx, evaluation.consignment_id)
    requirements = list(
        db.scalars(
            select(Requirement)
            .where(Requirement.evaluation_id == evaluation.id)
            .order_by(Requirement.requirement_code)
        )
    )
    sources = [
        exists(db, Source, i) for i in sorted({s for r in requirements for s in r.source_ids})
    ]
    binding = (
        db.get(Binding, evaluation.binding_revision_id) if evaluation.binding_revision_id else None
    )
    refs = (
        [
            binding.binding_json["movement_document"],
            *binding.binding_json.get("supporting_documents", []),
        ]
        if binding
        else []
    )
    shared_refs = [
        {
            "document_id": r["document_id"],
            "document_type": db.get(context.Document, r["document_id"]).document_type,
            "document_version_id": r["document_version_id"],
            "reviewed_fact_revision_id": r["reviewed_fact_revision_id"],
            "source_manifest_hash": next(
                (
                    d["source_hash"]
                    for d in evaluation.snapshot_json.get("documents", [])
                    if d["reference"]["document_version_id"] == r["document_version_id"]
                ),
                None,
            ),
            "fact_hash": next(
                (
                    d["fact_hash"]
                    for d in evaluation.snapshot_json.get("documents", [])
                    if d["reference"]["document_version_id"] == r["document_version_id"]
                ),
                None,
            ),
        }
        for r in refs
        if public_records.readable_version(db, ctx, r["document_version_id"])
    ]
    body = {
        "schema": "PH4_EVIDENCE_MANIFEST_V1",
        "evaluation_id": evaluation.id,
        "evaluation_hash": evaluation.evaluation_hash,
        "dependency_hash": evaluation.dependency_hash,
        "engine_version": evaluation.engine_version,
        "execution_mode": evaluation.execution_mode,
        "action": evaluation.action,
        "decision": evaluation.decision,
        "evaluated_at": view(evaluation)["evaluated_at"],
        "valid_until": view(evaluation)["valid_until"],
        "freshness": evaluations.current(db, evaluation, trade, cn),
        "requirements": [public_records.requirement(db, ctx, r) for r in requirements],
        "documents": shared_refs,
        "sources": [
            {
                "id": s.id,
                "title": s.title,
                "official_url": s.official_url,
                "source_kind": s.source_kind,
                "source_sha256": s.source_sha256,
                "interpretation_note": s.source_json["interpretation_note"],
            }
            for s in sources
        ],
        "registry_manifest": evaluation.registry_manifest_json,
        "coverage": evaluation.coverage_json,
        "limitations": evaluation.limitations_json,
        "private_declarations": "REDACTED",
    }
    frozen = {key: value for key, value in body.items() if key != "freshness"}
    body["decision_manifest_hash"] = digest(frozen)
    body["decision_manifest"] = frozen
    if token:
        packet, ack, review = (
            db.get(Packet, token.packet_id),
            db.get(PacketAck, token.acknowledgment_id),
            db.get(ReleaseReview, token.approval_id),
        )
        body["dispatch"] = {
            "authorisation_id": token.id,
            "packet_id": packet.id,
            "packet_hash": packet.packet_hash,
            "acknowledgment_id": ack.id,
            "review_id": review.id,
            "assignment_id": token.assignment_id,
            "consumed_event_id": token.consumed_event_id,
            "effective_state": dispatch.read(db, ctx, token.id)["effective_state"],
        }
    from .evidence_graph import build

    body["graph"] = build(db, evaluation, shared_refs, body["sources"])
    body["manifest_hash"] = digest(body)
    return body


def constraints(db, ctx, ident, action):
    trade, cn, _ = context.access(db, ctx, ident)
    state = readiness(db, ctx, ident, action)
    _, registry, _ = governance.resolve(db, trade.execution_mode)
    evaluation = state["evaluation"]
    head = context.heads(db, cn)
    fact = (
        db.get(context.Fact, head.current_fact_revision_id)
        if head and head.current_fact_revision_id
        else None
    )
    declared = fact.facts_json if fact else {}
    from app.operations.models import Assignment

    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    requirements = evaluation["requirements"] if evaluation else []
    hard = []
    for code, target, operator, value, requirement_code in [
        (
            "ASSIGNED_VEHICLE",
            "vehicle.registration_number",
            "EQ",
            assignment.vehicle_snapshot.get("registration_number") if assignment else None,
            "TRANSPORT_ASSURANCE",
        ),
        (
            "PAYLOAD_CEILING",
            "cargo.gross_weight_kg",
            "LTE",
            assignment.vehicle_snapshot.get("declared_payload_capacity_kg") if assignment else None,
            "LOADING_MANIFEST",
        ),
        (
            "DECLARED_CORRIDOR",
            "route.state_sequence",
            "EQ",
            [
                cn.pickup_address_snapshot["state_code"],
                *(declared.get("declared_transit_state_codes") or []),
                cn.delivery_address_snapshot["state_code"],
            ],
            "TRANSPORT_ASSURANCE",
        ),
        (
            "COMMODITY_PROFILE",
            "cargo.commodity_scope_codes",
            "EQ",
            declared.get("commodity_scope_codes"),
            "INVOICE_FORMALITIES",
        ),
        ("NO_TRANSSHIPMENT", "route.transshipments", "EQ", 0, "TRANSPORT_ASSURANCE"),
        (
            "CARRIED_REPRESENTATIONS",
            "driver.carried_documents",
            "REQUIRED",
            ["SUPPORTED_INVOICE", "APPLICABLE_EWB"],
            "CARRIED_DOCUMENTS",
        ),
    ]:
        requirement = next(
            (r for r in requirements if r["requirement_code"] == requirement_code), None
        )
        if requirement:
            hard.append(
                {
                    "code": code,
                    "target": target,
                    "operator": operator,
                    "value": value,
                    "requirement_id": requirement["id"],
                    "rule_id": requirement["rule_id"],
                    "class": requirement["rule_class"],
                    "source_ids": requirement["source_ids"],
                }
            )
    deadlines = (
        [
            {
                "code": "EVALUATION_VALIDITY",
                "timestamp": evaluation["valid_until"],
                "requirement_id": None,
                "class": "APPLICATION_POLICY",
                "meaning": "Earliest rule/evidence/policy boundary; reevaluation is required.",
            }
        ]
        if evaluation
        else []
    )
    for deadline in (evaluation or {}).get("coverage", {}).get("authority_deadlines", []):
        requirement = next(
            (r for r in requirements if r["requirement_code"] == deadline["requirement_code"]),
            None,
        )
        deadlines.append(
            {
                **deadline,
                "requirement_id": requirement["id"] if requirement else None,
                "rule_id": requirement["rule_id"] if requirement else None,
            }
        )
    for dimension in (
        (evaluation or {}).get("coverage", {}).get("independent_verification_dimensions", [])
    ):
        if dimension.get("fresh_until"):
            requirement = next(
                (
                    r
                    for r in requirements
                    if r["requirement_code"]
                    == (
                        "EWB_VALIDITY"
                        if dimension.get("check_type") == "EWB_AUTHORITY_LOOKUP"
                        else "EINVOICE_PROOF"
                        if dimension.get("check_type") == "IRN_LIVE_STATUS"
                        else "AUTHORITY_ASSURANCE"
                    )
                ),
                None,
            )
            deadlines.append(
                {
                    "code": "OBSERVATION_FRESHNESS",
                    "timestamp": dimension["fresh_until"],
                    "requirement_id": requirement["id"] if requirement else None,
                    "class": "APPLICATION_POLICY",
                    "meaning": "Published maximum observation age, not an authority expiry.",
                }
            )
    body = {
        "schema_version": 1,
        "contract": "COMPLIANCE_CONSTRAINTS_V1",
        "trade_id": trade.id,
        "accepted_trade_revision_id": trade.accepted_revision_id,
        "assignment_id": cn.active_assignment_id,
        "source_evaluation_id": evaluation["id"] if evaluation else None,
        "dependency_hash": db.get(Evaluation, evaluation["id"]).dependency_hash
        if evaluation
        else None,
        "evaluated_at": evaluation["evaluated_at"] if evaluation else None,
        "supported_scope": bool(
            evaluation
            and evaluation["coverage"].get("scope_predicate") is True
            and evaluation["decision"] != "UNSUPPORTED"
        ),
        "coverage_dimensions": [
            {"dimension": k, "status": v}
            for k, v in (evaluation or {}).get("coverage", {}).items()
            if v in ("COVERED", "NOT_ASSESSED", "UNSUPPORTED")
        ],
        "declared_corridor": {
            "origin_state_code": cn.pickup_address_snapshot["state_code"],
            "transit_state_codes": declared.get("declared_transit_state_codes"),
            "destination_state_code": cn.delivery_address_snapshot["state_code"],
            "basis": declared.get("corridor_declaration_basis"),
        },
        "hard_constraints": hard,
        "deadlines": deadlines,
        "missing_inputs": [
            r["requirement_code"] for r in requirements if r["outcome"] == "UNKNOWN"
        ],
        "constraint_id": digest(
            {
                "cn": cn.id,
                "action": action,
                "registry": registry,
                "context": state["context_version"],
            }
        ),
        "consignment_id": cn.id,
        "action": action,
        "execution_mode": trade.execution_mode,
        "freshness": "CURRENT"
        if evaluation
        and evaluation["freshness"] == "CURRENT"
        and evaluation["job_state"] == "COMPLETED"
        else "STALE",
        "evaluation_hash": evaluation["evaluation_hash"] if evaluation else None,
        "context_version": state["context_version"],
        "registry_epoch_manifest": registry,
        "dispatch_eligible": state["state"] == "READY",
        "requirements": evaluation["requirements"] if evaluation else [],
        "blockers": state["reasons"],
        "allowed_transit_states": declared.get("declared_transit_state_codes"),
        "valid_until": evaluation["valid_until"] if evaluation else None,
        "coverage": evaluation["coverage"] if evaluation else {},
        "limitations": [
            "Constraint handoff only; no optimization, freight price prediction "
            "or government clearance."
        ],
        "source_references": registry["packs"],
    }
    body["constraint_hash"] = digest(body)
    return body
