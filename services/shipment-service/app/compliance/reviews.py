"""Append-only decisions: correcting a case never changes a legal requirement result."""

from sqlalchemy import select

from app.operations.access import exists, fail

from . import context, evaluations
from .clock import instant
from .ledger import independent, record, view
from .models import CaseAction, Hold, HoldEvent, ReleaseReview, Requirement, ReviewCase, Rule


def manual_review(db, ctx, ident, payload):
    from app.document_desk.access import version as document_access
    from app.document_desk.models import ManualAttestation

    from .models import ManualEvidence, ManualReview

    observation = exists(db, ManualAttestation, ident)
    _, doc, trade = document_access(
        db, ctx, observation.document_version_id, "document.manual_observation.review", True
    )
    independent(ctx, observation.actor_user_id)
    structured = db.scalar(
        select(ManualEvidence).where(ManualEvidence.attestation_id == observation.id)
    )
    if (
        not structured
        or not structured.supporting_attachment_ids
        or doc.effective_fact_revision_id != observation.fact_revision_id
    ):
        fail(
            "REQUIRED_EVIDENCE_MISSING",
            "Review requires current submitted facts, structured observed fields "
            "and supporting portal evidence.",
        )
    from app.operations.models import Attachment

    for attachment_id in structured.supporting_attachment_ids:
        if exists(db, Attachment, attachment_id).security_state != "CLEAN":
            fail("REQUIRED_EVIDENCE_MISSING", "Supporting observation evidence must remain clean.")
    review = ManualReview(
        reviewer_organisation_id=ctx.org_id,
        attestation_id=observation.id,
        decision=payload.decision,
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(review)
    record(db, ctx, "MANUAL_OBSERVATION_REVIEWED", review, trade.id)
    return view(review)


def cases(db, ctx, ident):
    context.access(db, ctx, ident)
    return {
        "items": [
            {
                **view(c),
                "etag": f'"{c.row_version}"',
                "actions": [
                    view(a)
                    for a in db.scalars(
                        select(CaseAction)
                        .where(CaseAction.case_id == c.id)
                        .order_by(CaseAction.created_at, CaseAction.id)
                    )
                ],
            }
            for c in db.scalars(
                select(ReviewCase)
                .where(ReviewCase.consignment_id == ident)
                .order_by(ReviewCase.created_at.desc(), ReviewCase.id)
            )
        ]
    }


def case_permission(payload):
    return (
        "compliance.case.resolve"
        if payload.followup_evaluation_id
        or payload.action in {"ACKNOWLEDGE_POLICY_WARNING", "APPLY_PUBLISHED_EXCEPTION"}
        else "compliance.case.comment"
    )


def case_action(db, ctx, ident, payload):
    row = exists(db, ReviewCase, ident)
    trade, _, side = context.access(
        db, ctx, row.consignment_id, case_permission(payload), lock=True
    )
    requirement = exists(db, Requirement, row.requirement_id)
    if ctx.if_match != f'"{row.row_version}"':
        fail("EVALUATION_STALE", "Case changed; reload its current ETag.", status=412)
    if (
        str(payload.evaluation_id) != row.origin_evaluation_id
        or str(payload.requirement_id) != requirement.id
    ):
        fail("EVALUATION_STALE", "Respond to the exact case/evaluation/requirement.")
    if payload.action == "ACKNOWLEDGE_POLICY_WARNING":
        definition = db.get(Rule, requirement.rule_id).rule_json
        if (
            side != "SELLER"
            or requirement.mandatory
            or not definition["waivable_warning"]
            or requirement.rule_class != "APPLICATION_POLICY"
        ):
            fail(
                "MANDATORY_REQUIREMENT_NOT_WAIVABLE",
                "Only a published waivable application-policy warning can be acknowledged.",
            )
    if payload.action == "APPLY_PUBLISHED_EXCEPTION":
        fail(
            "UNSUPPORTED_SCOPE",
            "The initial ordinary-goods profile publishes no exception predicates. "
            "Request a scope extension; a case cannot waive a blocker.",
        )
    from app.document_desk.access import version as document_access

    for document_id in payload.document_version_ids:
        _, doc, _ = document_access(db, ctx, document_id)
        if doc.trade_id != trade.id:
            fail("NOT_FOUND", "Evidence not found.", status=404)
    from app.document_desk.models import VerificationCheck, VerificationResult

    for result_id in payload.verification_result_ids:
        check = exists(
            db, VerificationCheck, exists(db, VerificationResult, result_id).verification_check_id
        )
        _, doc, _ = document_access(db, ctx, check.document_version_id)
        if doc.trade_id != trade.id:
            fail("NOT_FOUND", "Observation not found in this trade.", status=404)
    if payload.fact_revision_id:
        from .models import Fact

        if exists(db, Fact, payload.fact_revision_id).consignment_id != row.consignment_id:
            fail("NOT_FOUND", "Declaration not found in this consignment.", status=404)
    action = CaseAction(
        case_id=row.id,
        evaluation_id=row.origin_evaluation_id,
        requirement_id=requirement.id,
        action=payload.action,
        reason=payload.reason,
        action_json=payload.model_dump(mode="json"),
        created_by_user_id=ctx.user.id,
    )
    db.add(action)
    db.flush()
    if payload.action == "ACKNOWLEDGE_POLICY_WARNING":
        row.status, row.current_resolution_action_id = "ACKNOWLEDGED", action.id
    elif payload.followup_evaluation_id:
        followup, _, cn, _ = evaluations.exact(db, ctx, str(payload.followup_evaluation_id))
        matched = db.scalar(
            select(Requirement).where(
                Requirement.evaluation_id == followup.id,
                Requirement.requirement_code == requirement.requirement_code,
            )
        )
        if (
            cn.id != row.consignment_id
            or evaluations.current(db, followup, trade, cn) != "CURRENT"
            or not matched
            or matched.outcome not in {"SATISFIED", "NOT_APPLICABLE"}
        ):
            fail(
                "COMPLIANCE_NOT_READY",
                "Case resolution needs a fresh same-consignment evaluation proving correction.",
            )
        row.status, row.current_resolution_action_id = "RESOLVED_BY_REEVALUATION", action.id
    row.row_version += 1
    record(db, ctx, "COMPLIANCE_CASE_ACTION_RECORDED", action, trade.id)
    return view(action)


def release(db, ctx, ident, payload):
    row, trade, cn, _ = evaluations.exact(db, ctx, ident, "dispatch.release.approve", True)
    from .review_authority import release_preparers

    for prepared_by in release_preparers(db, row):
        independent(ctx, prepared_by)
    if (
        payload.evaluation_hash != row.evaluation_hash
        or evaluations.current(db, row, trade, cn) != "CURRENT"
    ):
        fail("EVALUATION_STALE", "Review the exact current unexpired evaluation hash.", status=412)
    if payload.decision == "APPROVE_RELEASE":
        if row.decision not in {"ELIGIBLE_FOR_REVIEW", "NEEDS_REVIEW"}:
            fail(
                "COMPLIANCE_NOT_READY",
                "Mandatory blockers and unsupported scope cannot be approved.",
            )
        for requirement in db.scalars(
            select(Requirement).where(Requirement.evaluation_id == row.id)
        ):
            if requirement.outcome not in {"FAILED", "UNKNOWN"}:
                continue
            if requirement.mandatory:
                fail(
                    "COMPLIANCE_NOT_READY",
                    "An unknown or failed mandatory requirement blocks release.",
                )
            acceptable = db.scalar(
                select(CaseAction).where(
                    CaseAction.id.in_([str(i) for i in payload.acknowledged_warning_action_ids]),
                    CaseAction.evaluation_id == row.id,
                    CaseAction.requirement_id == requirement.id,
                    CaseAction.action == "ACKNOWLEDGE_POLICY_WARNING",
                )
            )
            if not acceptable:
                fail(
                    "COMPLIANCE_NOT_READY",
                    "Record and select a published policy-warning acknowledgment first.",
                )
    decision = ReleaseReview(
        evaluation_id=row.id,
        evaluation_hash=row.evaluation_hash,
        decision=payload.decision,
        acknowledged_warning_action_ids=[str(i) for i in payload.acknowledged_warning_action_ids],
        reason=payload.reason,
        reviewer_organisation_id=ctx.org_id,
        valid_until=row.valid_until,
        created_by_user_id=ctx.user.id,
    )
    db.add(decision)
    record(
        db, ctx, "COMPLIANCE_RELEASE_REVIEWED", decision, trade.id, {"decision": payload.decision}
    )
    return view(decision)


def hold(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "compliance.hold.create", lock=True)
    from app.document_desk.access import version as document_access
    from app.document_desk.models import VerificationCheck, VerificationResult
    from app.operations.models import Event

    for ref in payload.evidence_references:
        if ref.document_version_id or ref.verification_result_id:
            source = ref.document_version_id
            if ref.verification_result_id:
                result = exists(db, VerificationResult, ref.verification_result_id)
                source = exists(
                    db, VerificationCheck, result.verification_check_id
                ).document_version_id
            _, document, _ = document_access(db, ctx, source)
            if document.trade_id != trade.id:
                fail("NOT_FOUND", "Hold evidence not found in this trade.", status=404)
        if ref.requirement_id:
            requirement = exists(db, Requirement, ref.requirement_id)
            if (
                exists(db, evaluations.Evaluation, requirement.evaluation_id).consignment_id
                != cn.id
            ):
                fail("NOT_FOUND", "Hold requirement not found in this consignment.", status=404)
        if (
            ref.movement_event_id
            and exists(db, Event, ref.movement_event_id).consignment_id != cn.id
        ):
            fail("NOT_FOUND", "Hold movement evidence not found.", status=404)
    row = Hold(
        trade_id=trade.id,
        consignment_id=cn.id,
        reason_code=payload.reason_code,
        reason=payload.reason,
        evidence_refs_json=[
            ref.model_dump(mode="json", exclude_none=True) for ref in payload.evidence_references
        ],
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "COMPLIANCE_HOLD_CREATED", row)
    return view(row)


def release_request(db, ctx, ident, payload):
    row = exists(db, Hold, ident)
    hold_access(db, ctx, row, "compliance.hold.release.request")
    if not row.active:
        fail("COMPLIANCE_NOT_READY", "Hold is already released.")
    event = HoldEvent(
        hold_id=row.id,
        event_type="RELEASE_REQUESTED",
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(event)
    record(db, ctx, "COMPLIANCE_HOLD_RELEASE_REQUESTED", event, row.trade_id)
    return view(event)


def release_approval(db, ctx, ident, payload):
    row = exists(db, Hold, ident)
    hold_access(db, ctx, row, "compliance.hold.release.approve")
    request = exists(db, HoldEvent, payload.release_request_event_id)
    if request.hold_id != row.id or request.event_type != "RELEASE_REQUESTED" or not row.active:
        fail("COMPLIANCE_NOT_READY", "Select this active hold's release request.")
    independent(ctx, request.created_by_user_id)
    event = HoldEvent(
        hold_id=row.id,
        event_type="RELEASE_APPROVED",
        reason=payload.reason,
        release_request_event_id=request.id,
        created_by_user_id=ctx.user.id,
    )
    db.add(event)
    row.active, row.row_version = False, row.row_version + 1
    record(db, ctx, "COMPLIANCE_HOLD_RELEASED", event, row.trade_id)
    return {**view(event), "released_at": instant(db).isoformat()}


def hold_access(db, ctx, hold, permission):
    if hold.consignment_id:
        return context.access(db, ctx, hold.consignment_id, permission, lock=True)
    from app.operations.access import party

    return party(db, ctx, hold.trade_id, permission, lock=True)
