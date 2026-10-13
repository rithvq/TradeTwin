from sqlalchemy import func, select

from app.document_desk.access import version as document_access
from app.operations.access import aligned, exists, fail
from app.operations.models import Assignment, ConsignmentItem
from app.trades.terms import digest

from . import context
from .clock import instant
from .ledger import check_context, independent, record, view
from .models import Fact, FactReview, Manifest, TransportEvidence, TransportReview


def scoped_document(db, ctx, ident, trade_id, reviewed=False):
    source, doc, _ = document_access(db, ctx, ident)
    if doc.trade_id != trade_id or doc.lifecycle_status == "ARCHIVED":
        fail("NOT_FOUND", "Source evidence not found in this trade.", status=404)
    if reviewed and (source.id != doc.current_version_id or not doc.effective_fact_revision_id):
        fail(
            "REQUIRED_EVIDENCE_MISSING",
            "Submit a reviewed current source before using it as a declaration basis.",
        )
    return source, doc


def next_number(db, model, cn):
    return (
        db.scalar(select(func.max(model.revision_number)).where(model.consignment_id == cn.id)) or 0
    ) + 1


def prepare(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "compliance.facts.prepare", True, True)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    aligned(cn)
    inherited = context.inherited(db, trade, cn)
    data = payload.facts.model_dump(mode="json")
    transit = data["declared_transit_state_codes"]
    if transit is not None and {
        inherited["origin_state_code"],
        inherited["destination_state_code"],
    } & set(transit):
        fail(
            "VALIDATION_ERROR",
            "Transit states contain intermediate states only.",
            "facts.declared_transit_state_codes",
            422,
        )
    provenance = {}
    for key in data:
        if key == "field_provenance":
            continue
        item = data["field_provenance"].get(key) or {"origin": "USER_DECLARATION"}
        if item.get("origin") == "REVIEWED_DOCUMENT":
            if item.get("source_entity_type") != "DOCUMENT_VERSION" or not item.get(
                "source_entity_id"
            ):
                fail(
                    "VALIDATION_ERROR",
                    "Reviewed-document provenance needs an exact source version.",
                    f"facts.field_provenance.{key}",
                    422,
                )
            scoped_document(db, ctx, item["source_entity_id"], trade.id, True)
        provenance[key] = {
            **item,
            "declared_by_user_id": ctx.user.id,
            "declared_at": instant(db).isoformat(),
        }
    for key in (
        "corridor_basis_document_version_ids",
        "taxability_basis_document_version_ids",
        "classification_basis_document_version_ids",
        "claimed_exception_basis_document_version_ids",
    ):
        for source_id in data[key]:
            scoped_document(db, ctx, source_id, trade.id, True)
    if data["seller_turnover_declaration_id"]:
        from .models import Turnover
        from .turnover import private_access

        declaration = exists(db, Turnover, data["seller_turnover_declaration_id"])
        private_access(db, ctx, declaration.seller_organisation_id, "turnover.read")
    provenance.update(
        {
            key: {
                "origin": "INHERITED",
                "source_entity_type": "ACCEPTED_TRADE_REVISION",
                "source_entity_id": trade.accepted_revision_id,
                "source_field_path": key,
            }
            for key in inherited
        }
    )
    combined = {**data, **inherited, "field_provenance": provenance}
    row = Fact(
        trade_id=trade.id,
        consignment_id=cn.id,
        revision_number=next_number(db, Fact, cn),
        accepted_trade_revision_id=trade.accepted_revision_id,
        assignment_id=cn.active_assignment_id,
        schema_version=1,
        prepared_context_version=context.version(db, trade.id),
        inherited_hash=digest(inherited),
        submitted_for_review=payload.submit_for_review,
        facts_json=combined,
        provenance_json=provenance,
        content_hash=digest(combined),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "COMPLIANCE_FACTS_PREPARED", row)
    return {
        "id": row.id,
        "content_hash": row.content_hash,
        "review_state": "SUBMITTED" if row.submitted_for_review else "DRAFT",
        "facts": combined,
        "context_version": context.version(db, trade.id),
    }


def review(db, ctx, ident, payload):
    row = exists(db, Fact, ident)
    trade, cn, _ = context.access(
        db, ctx, row.consignment_id, "compliance.facts.review", True, True
    )
    independent(ctx, row.created_by_user_id)
    head = context.heads(db, cn, True)
    effective = head.current_fact_revision_id == row.id
    if (
        not row.submitted_for_review
        or (not effective and row.prepared_context_version != context.version(db, trade.id))
        or digest(context.inherited(db, trade, cn)) != row.inherited_hash
    ):
        fail(
            "EVALUATION_STALE",
            "Preparation's inherited context changed or the draft was not submitted.",
            status=412,
        )
    decision = FactReview(
        fact_revision_id=row.id,
        decision=payload.decision,
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(decision)
    if decision.decision == "APPROVE_DECLARATION":
        head.current_fact_revision_id = row.id
        head.row_version += 1
    elif effective:
        head.current_fact_revision_id = None
        head.row_version += 1
    record(
        db,
        ctx,
        "COMPLIANCE_FACTS_APPROVED"
        if decision.decision == "APPROVE_DECLARATION"
        else "COMPLIANCE_FACTS_RETURNED",
        decision,
        trade.id,
    )
    return {
        "id": decision.id,
        "fact_revision_id": row.id,
        "decision": decision.decision,
        "context_version": context.version(db, trade.id),
    }


def manifest(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "shipment.loading_manifest.prepare", True, True)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    if cn.movement_status != "NOT_STARTED" or cn.planning_status != "PREPARING":
        fail(
            "COMPLIANCE_NOT_READY",
            "Prepare an unpicked consignment before declaring the loading manifest.",
        )
    assignment = (
        exists(db, Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    )
    if not assignment or assignment.status != "ACCEPTED":
        fail("ASSIGNMENT_CHANGED", "An accepted vehicle/driver assignment is required.")
    goods = list(db.scalars(select(ConsignmentItem).where(ConsignmentItem.consignment_id == cn.id)))
    submitted = {str(i.consignment_item_id): i for i in payload.manifest.items}
    if len(submitted) != len(payload.manifest.items) or set(submitted) != {i.id for i in goods}:
        fail("LOADING_MANIFEST_MISMATCH", "Declare every allocated line exactly once.")
    for item in goods:
        declared = submitted[item.id]
        if (
            str(declared.trade_line_ref) != item.line_ref
            or declared.loaded_quantity != item.allocated_quantity
            or declared.uqc != item.uqc
        ):
            fail(
                "LOADING_MANIFEST_MISMATCH",
                "Quantity, order-line identity and UQC must match the allocation.",
            )
    from decimal import Decimal

    if payload.manifest.actual_prepared_gross_weight_kg > Decimal(
        assignment.vehicle_snapshot["declared_payload_capacity_kg"]
    ):
        fail(
            "LOADING_MANIFEST_MISMATCH",
            "Prepared declared weight exceeds the accepted vehicle capacity.",
        )
    if payload.manifest.package_type != cn.plan_json["package_type"]:
        fail("LOADING_MANIFEST_MISMATCH", "Use the prepared consignment's package type.")
    for source_id in payload.manifest.measurement_document_version_ids:
        scoped_document(db, ctx, source_id, trade.id, True)
    data = {
        **payload.manifest.model_dump(mode="json"),
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "accepted_trade_revision_id": trade.accepted_revision_id,
        "assignment_id": assignment.id,
        "prepared_by_user_id": ctx.user.id,
        "prepared_at": instant(db).isoformat(),
    }
    row = Manifest(
        trade_id=trade.id,
        consignment_id=cn.id,
        assignment_id=assignment.id,
        accepted_trade_revision_id=trade.accepted_revision_id,
        revision_number=next_number(db, Manifest, cn),
        manifest_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    head = context.heads(db, cn, True)
    head.current_loading_manifest_revision_id = row.id
    head.row_version += 1
    record(db, ctx, "LOADING_MANIFEST_PREPARED", row)
    return {**view(row), "context_version": context.version(db, trade.id)}


def transport(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "transport.evidence.prepare", False, True)
    assignment = exists(db, Assignment, payload.assignment_id)
    if assignment.id != cn.active_assignment_id or assignment.status != "ACCEPTED":
        fail("ASSIGNMENT_CHANGED", "Use the current accepted assignment.")
    subjects = {
        "VEHICLE": assignment.vehicle_id,
        "DRIVER": assignment.driver_user_id,
        "CARRIER": assignment.carrier_organization_id,
        "CONSIGNMENT": cn.id,
    }
    expected_subject = (
        "DRIVER"
        if payload.evidence_type == "DRIVER_LICENCE"
        else "CONSIGNMENT"
        if payload.evidence_type == "CARGO_INSURANCE"
        else "VEHICLE"
    )
    if payload.subject_type != expected_subject:
        fail(
            "VALIDATION_ERROR", "Evidence must identify its actual assignment subject.", status=422
        )
    if str(payload.subject_id) != subjects[payload.subject_type]:
        fail("NOT_FOUND", "Assignment evidence subject not found.", status=404)
    if (
        payload.evidence_type == "DRIVER_LICENCE"
        and ctx.org_id != assignment.carrier_organization_id
    ):
        fail(
            "FORBIDDEN",
            "Driver identity evidence must remain in the assigned carrier organisation.",
            status=403,
        )
    if payload.document_version_id:
        source, doc = scoped_document(db, ctx, payload.document_version_id, trade.id, True)
        if str(payload.reviewed_fact_revision_id) != doc.effective_fact_revision_id:
            fail(
                "REQUIRED_EVIDENCE_MISSING",
                "Use the exact submitted transport-source fact revision.",
            )
        if doc.document_type != payload.evidence_type:
            fail(
                "VALIDATION_ERROR",
                "Evidence type must match the registered source document.",
                status=422,
            )
        from app.document_desk.models import FactRevision

        captured = exists(db, FactRevision, payload.reviewed_fact_revision_id)
        source_number = captured.canonical_document_json.get("header", {}).get("document_number")
        if source_number and source_number != payload.document_number:
            fail(
                "REQUIRED_EVIDENCE_MISSING", "Transport number differs from reviewed source facts."
            )
    elif payload.source_mode in {"ORIGINAL_DOCUMENT", "ISSUER_DIGITAL_RECORD"}:
        fail(
            "REQUIRED_EVIDENCE_MISSING",
            "This source mode needs its actual secured document version.",
        )
    if (
        payload.source_mode in {"ISSUER_DIGITAL_RECORD", "AUTHORISED_LOOKUP"}
        and not payload.verification_result_id
    ):
        fail(
            "REQUIRED_EVIDENCE_MISSING",
            "Issuer/authorised evidence needs the matching authorised observation, "
            "not an uploaded screenshot.",
        )
    if payload.verification_result_id:
        from app.document_desk.models import VerificationCheck, VerificationResult

        result = exists(db, VerificationResult, payload.verification_result_id)
        check = exists(db, VerificationCheck, result.verification_check_id)
        data = result.result_json
        if check.document_version_id != str(
            payload.document_version_id
        ) or check.fact_revision_id != str(payload.reviewed_fact_revision_id):
            fail(
                "NOT_FOUND",
                "Observation must bind this exact reviewed transport source.",
                status=404,
            )
        if payload.source_mode in {"ISSUER_DIGITAL_RECORD", "AUTHORISED_LOOKUP"} and (
            check.check_type != "TRANSPORT_AUTHORITY_LOOKUP"
            or data.get("normalised_result", {}).get("evidence_type") != payload.evidence_type
            or data.get("normalised_result", {}).get("subject_id") != str(payload.subject_id)
            or data.get("normalised_result", {}).get("document_number") != payload.document_number
            or data.get("method") != "AUTHORISED_LOOKUP"
            or data.get("provider_environment")
            != ("SIMULATION" if trade.execution_mode == "SIMULATION" else "LIVE")
        ):
            fail(
                "REQUIRED_EVIDENCE_MISSING",
                "An upload or self-report cannot be labelled issuer-authorised evidence.",
            )
    if payload.parent_permit_evidence_revision_id:
        parent = exists(db, TransportEvidence, payload.parent_permit_evidence_revision_id)
        if parent.assignment_id != assignment.id or parent.evidence_type != "GOODS_PERMIT":
            fail("NOT_FOUND", "Parent permit evidence not found for this assignment.", status=404)
    data = {
        **payload.model_dump(mode="json"),
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "owner_organisation_id": ctx.org_id,
    }
    row = TransportEvidence(
        trade_id=trade.id,
        consignment_id=cn.id,
        assignment_id=assignment.id,
        owner_organisation_id=ctx.org_id,
        subject_type=payload.subject_type,
        subject_id=str(payload.subject_id),
        evidence_type=payload.evidence_type,
        document_version_id=str(payload.document_version_id)
        if payload.document_version_id
        else None,
        reviewed_fact_revision_id=str(payload.reviewed_fact_revision_id)
        if payload.reviewed_fact_revision_id
        else None,
        verification_result_id=str(payload.verification_result_id)
        if payload.verification_result_id
        else None,
        parent_permit_evidence_revision_id=str(payload.parent_permit_evidence_revision_id)
        if payload.parent_permit_evidence_revision_id
        else None,
        evidence_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "TRANSPORT_EVIDENCE_PREPARED", row)
    return {
        "id": row.id,
        "content_hash": row.content_hash,
        "review_status": "UNREVIEWED",
        "authority_observation": "NOT_ASSESSED",
        "source_mode": payload.source_mode,
    }


def transport_review(db, ctx, ident, payload):
    row = exists(db, TransportEvidence, ident)
    trade, _, _ = context.access(
        db, ctx, row.consignment_id, "transport.evidence.review", False, True
    )
    independent(ctx, row.created_by_user_id)
    if ctx.org_id != row.owner_organisation_id:
        fail(
            "FORBIDDEN",
            "Transport declaration review belongs to its owner organisation.",
            status=403,
        )
    if row.document_version_id:
        _, doc = scoped_document(db, ctx, row.document_version_id, trade.id, True)
        if doc.effective_fact_revision_id != row.reviewed_fact_revision_id:
            fail("REQUIRED_EVIDENCE_MISSING", "Review the exact current source revision.")
    decision = TransportReview(
        reviewer_organisation_id=ctx.org_id,
        evidence_revision_id=row.id,
        decision=payload.decision,
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(decision)
    record(
        db,
        ctx,
        "TRANSPORT_EVIDENCE_APPROVED"
        if decision.decision == "APPROVE_DECLARATION"
        else "TRANSPORT_EVIDENCE_RETURNED",
        decision,
        trade.id,
    )
    return {"id": decision.id, "evidence_revision_id": row.id, "decision": decision.decision}
