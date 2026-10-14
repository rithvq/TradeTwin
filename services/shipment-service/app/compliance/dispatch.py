"""Assignment-bound packets and short-lived, single-use platform dispatch authorisation."""

from decimal import Decimal

from sqlalchemy import select

from app.document_desk.models import Artifact, Asset, Document, Version
from app.operations.access import exists, fail
from app.operations.models import Assignment, Attachment
from app.trades.access import membership
from app.trades.models import Grant, User
from app.trades.terms import digest

from . import context, evaluations
from .clock import aware, instant
from .ledger import check_context, record, valid_window, view
from .models import (
    Authorization,
    AuthorizationEvent,
    Binding,
    Evaluation,
    Manifest,
    Packet,
    PacketAck,
    PacketItem,
    ReleaseReview,
    Requirement,
    Reservation,
    ReservationEvent,
)


def live_grant(db, user_id, org_id, trade_id, permission):
    user = exists(db, User, user_id)
    if not user.active:
        fail("FORBIDDEN", "Account no longer authorised.", status=403)
    member = membership(db, user, org_id)
    now = instant(db)
    grants = list(
        db.scalars(
            select(Grant).where(
                Grant.membership_id == member.id,
                Grant.permission_code == permission,
                Grant.revoked_at.is_(None),
            )
        )
    )
    eligible = [
        g
        for g in grants
        if g.trade_id in {None, trade_id} and (g.expires_at is None or now < aware(g.expires_at))
    ]
    if not eligible:
        fail("FORBIDDEN", "Required permission expired or was revoked.", status=403)
    return (
        None
        if any(g.expires_at is None for g in eligible)
        else max(aware(g.expires_at) for g in eligible)
    )


def approval(db, evaluation, ident):
    row = exists(db, ReleaseReview, ident)
    latest = db.scalar(
        select(ReleaseReview)
        .where(ReleaseReview.evaluation_id == evaluation.id)
        .order_by(ReleaseReview.created_at.desc(), ReleaseReview.id.desc())
    )
    if (
        row.evaluation_id != evaluation.id
        or row.evaluation_hash != evaluation.evaluation_hash
        or row.decision != "APPROVE_RELEASE"
        or row.id != latest.id
        or not valid_window(db, None, row.valid_until)
    ):
        fail(
            "COMPLIANCE_NOT_READY",
            "Select the current exact unexpired independent release approval.",
        )
    live_grant(
        db,
        row.created_by_user_id,
        row.reviewer_organisation_id,
        evaluation.trade_id,
        "dispatch.release.approve",
    )
    return row


def ready_evaluation(db, ctx, ident, claimed_hash, action, permission):
    row, trade, cn, _ = evaluations.exact(db, ctx, ident, permission)
    if (
        row.evaluation_hash != claimed_hash
        or row.action != action
        or row.decision not in {"ELIGIBLE_FOR_REVIEW", "NEEDS_REVIEW"}
    ):
        fail("COMPLIANCE_NOT_READY", "An eligible exact action-specific evaluation is required.")
    if evaluations.current(db, row, trade, cn) != "CURRENT":
        fail("EVALUATION_STALE", "Evaluation dependencies or validity changed.", status=412)
    return row, trade, cn


def prepare_packet(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "dispatch.packet.prepare", lock=True)
    evaluation, _, target = ready_evaluation(
        db,
        ctx,
        str(payload.evaluation_id),
        payload.evaluation_hash,
        payload.action,
        "dispatch.packet.prepare",
    )
    if target.id != cn.id:
        fail("NOT_FOUND", "Evaluation not found.", status=404)
    review = approval(db, evaluation, payload.approval_id)
    assignment = exists(db, Assignment, cn.active_assignment_id)
    if assignment.status != "ACCEPTED" or not assignment.driver_user_id:
        fail("ASSIGNMENT_CHANGED", "An accepted assigned driver is required.")
    binding = exists(db, Binding, evaluation.binding_revision_id)
    refs = [
        binding.binding_json["movement_document"],
        *binding.binding_json.get("supporting_documents", []),
    ]
    allowed_versions = {r["document_version_id"] for r in refs}
    items, required_invoice, required_ewb = [], False, False
    carry_rule = db.scalar(
        select(Requirement).where(
            Requirement.evaluation_id == evaluation.id,
            Requirement.requirement_code == "CARRIED_DOCUMENTS",
        )
    )
    for choice in payload.selected_representations:
        requirement = exists(db, Requirement, choice.requirement_id)
        if (
            requirement.evaluation_id != evaluation.id
            or requirement.outcome != "SATISFIED"
            or requirement.id != carry_rule.id
        ):
            fail(
                "COMPLIANCE_NOT_READY",
                "Packet choices must bind the satisfied carried-document requirement.",
            )
        source = choice.source_reference
        version_id = source.get("document_version_id")
        if (
            set(source) - {"document_version_id", "attachment_id", "artifact_id"}
            or version_id not in allowed_versions
        ):
            fail("NOT_FOUND", "Select an exact bound source representation.", status=404)
        version = exists(db, Version, version_id)
        document = exists(db, Document, version.document_id)
        artifact, attachment, source_hash = None, None, None
        if choice.representation_type in {"INVOICE_COPY", "PAPER_INVOICE_REFERENCE"}:
            if (
                document.id != binding.binding_json["movement_document"]["document_id"]
                or document.document_type != "TAX_INVOICE"
                or choice.carry_method not in {"PAPER_COPY", "DIGITAL_OFFLINE_COPY"}
            ):
                fail(
                    "COMPLIANCE_NOT_READY",
                    "Use the bound invoice and a supported offline/paper carry method.",
                )
            required_invoice = True
        elif choice.representation_type in {"EWB_COPY", "EWB_NUMBER"}:
            if document.document_type != "EWAY_BILL_COPY" or choice.carry_method not in {
                "PAPER_COPY",
                "DIGITAL_OFFLINE_COPY",
                "EWB_NUMBER_AVAILABLE",
            }:
                fail("COMPLIANCE_NOT_READY", "Use the exact bound e-way bill representation.")
            required_ewb = True
        elif choice.representation_type == "SIGNED_IRN_QR":
            artifact = exists(db, Artifact, source.get("artifact_id"))
            if (
                artifact.document_version_id != version.id
                or artifact.content_type != "image/png"
                or artifact.artifact_type != "SIGNED_QR_IMAGE"
                or choice.carry_method != "SIGNED_IRN_QR_ELECTRONIC"
            ):
                fail(
                    "UNSUPPORTED_SCOPE",
                    "Only a verified signed-QR image is supported, not decoded JWS/JSON.",
                )
            from app.document_desk.models import VerificationResult

            verified = any(
                db.get(VerificationResult, i).result_json.get("signed_qr_artifact_id")
                == artifact.id
                for i in binding.binding_json.get("verification_result_ids", [])
            )
            proof = db.scalar(
                select(Requirement).where(
                    Requirement.evaluation_id == evaluation.id,
                    Requirement.requirement_code == "EINVOICE_PROOF",
                )
            )
            if not verified or not proof or proof.outcome != "SATISFIED":
                fail(
                    "REQUIRED_EVIDENCE_MISSING",
                    "Electronic QR substitution requires the selected "
                    "covered-field signature and IRN proof.",
                )
            required_invoice, source_hash = True, artifact.sha256
        else:
            fail(
                "UNSUPPORTED_SCOPE",
                "This carried representation is not enabled by the initial profile.",
            )
        if not artifact and choice.representation_type not in {
            "EWB_NUMBER",
            "PAPER_INVOICE_REFERENCE",
        }:
            attachment = exists(db, Attachment, source.get("attachment_id"))
            asset = db.scalar(
                select(Asset).where(
                    Asset.document_version_id == version.id, Asset.attachment_id == attachment.id
                )
            )
            if (
                not asset
                or attachment.security_state != "CLEAN"
                or attachment.sha256 != asset.asset_sha256
                or attachment.content_type not in {"application/pdf", "image/png", "image/jpeg"}
            ):
                fail(
                    "REQUIRED_EVIDENCE_MISSING",
                    "Use a clean exact PDF/image source, "
                    "never an unrestricted structured financial payload.",
                )
            source_hash = asset.asset_sha256
        items.append(
            {
                "requirement_id": requirement.id,
                "document_version_id": version.id,
                "artifact_id": artifact.id if artifact else None,
                "representation_type": choice.representation_type,
                "carry_method": choice.carry_method,
                "allowed_recipient_user_id": assignment.driver_user_id,
                "sensitivity_class": "DISPATCH_ONLY",
                "source_sha256": source_hash,
                "limitations_json": [
                    "Selected consignment/assignment only; not generic document access."
                ],
                "source_reference_json": {
                    **source,
                    "printed_identifiers": _printed_identifiers(db, version.id),
                },
            }
        )
    ewb = db.scalar(
        select(Requirement).where(
            Requirement.evaluation_id == evaluation.id,
            Requirement.requirement_code == "EWB_REQUIRED",
        )
    )
    if not required_invoice or (ewb and ewb.applicability == "APPLICABLE" and not required_ewb):
        fail(
            "REQUIRED_EVIDENCE_MISSING",
            "Packet needs an invoice and, when applicable, an e-way bill copy or number.",
        )
    body = {
        "schema": "PH4_PACKET_V1",
        "assignment_id": assignment.id,
        "consignment_id": cn.id,
        "action": payload.action,
        "execution_mode": trade.execution_mode,
        "evaluation_hash": evaluation.evaluation_hash,
        "items": items,
        "limitations": ["Platform dispatch authorisation; no government clearance."],
    }
    row = Packet(
        prepared_by_organisation_id=ctx.org_id,
        trade_id=trade.id,
        consignment_id=cn.id,
        action=payload.action,
        execution_mode=trade.execution_mode,
        assignment_id=assignment.id,
        evaluation_id=evaluation.id,
        approval_id=review.id,
        loading_manifest_revision_id=evaluation.loading_manifest_revision_id,
        dependency_hash=evaluation.dependency_hash,
        packet_hash=digest(body),
        valid_until=min(
            aware(evaluation.valid_until),
            aware(review.valid_until),
            aware(assignment.booking_end_at),
        ),
        manifest_json=body,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    for item in items:
        db.add(PacketItem(packet_id=row.id, **item, created_by_user_id=ctx.user.id))
    record(db, ctx, "DISPATCH_PACKET_PREPARED", row)
    return packet_view(db, ctx, row.id)


def _printed_identifiers(db, version_id):
    from app.document_desk.models import FactRevision

    document = exists(db, Document, exists(db, Version, version_id).document_id)
    canonical = exists(
        db, FactRevision, document.effective_fact_revision_id
    ).canonical_document_json
    return {
        "document_number": canonical.get("header", {}).get("document_number"),
        "document_date": canonical.get("header", {}).get("issue_date"),
        "eway_bill_number": canonical.get("eway_bill", {}).get("eway_bill_number"),
    }


def packet_current(db, packet, trade, cn):
    if cn.active_assignment_id != packet.assignment_id:
        fail("ASSIGNMENT_CHANGED", "Packet is bound to a different assignment.")
    row = exists(db, Evaluation, packet.evaluation_id)
    if (
        not valid_window(db, None, packet.valid_until)
        or evaluations.current(db, row, trade, cn) != "CURRENT"
    ):
        fail("PACKET_STALE", "Packet expired or its evidence/assignment changed.", status=412)
    approval(db, row, packet.approval_id)
    live_grant(
        db,
        packet.created_by_user_id,
        packet.prepared_by_organisation_id,
        trade.id,
        "dispatch.packet.prepare",
    )
    return row


def packet_view(db, ctx, ident):
    packet = exists(db, Packet, ident)
    trade, cn, side = context.access(db, ctx, packet.consignment_id, "dispatch.packet.read")
    body = view(packet)
    body.pop("manifest_json")
    items = [
        view(i)
        for i in db.scalars(
            select(PacketItem).where(PacketItem.packet_id == packet.id).order_by(PacketItem.id)
        )
    ]
    body["items"] = (
        items
        if side == "SELLER"
        or ctx.user.id == db.get(Assignment, packet.assignment_id).driver_user_id
        else [
            {k: v for k, v in i.items() if k not in {"source_reference_json", "source_sha256"}}
            for i in items
        ]
    )
    try:
        packet_current(db, packet, trade, cn)
        body["effective_state"] = "CURRENT"
    except Exception as exc:
        from app.trades.errors import TradeError

        if not isinstance(exc, TradeError):
            raise
        body["effective_state"] = exc.code
    return body


def acknowledge(db, ctx, ident, payload):
    packet = exists(db, Packet, ident)
    trade, cn, _ = context.access(
        db, ctx, packet.consignment_id, "dispatch.packet.acknowledge", lock=True
    )
    packet_current(db, packet, trade, cn)
    assignment = exists(db, Assignment, packet.assignment_id)
    if (
        assignment.driver_user_id != ctx.user.id
        or str(payload.assignment_id) != assignment.id
        or payload.packet_hash != packet.packet_hash
    ):
        fail(
            "FORBIDDEN",
            "Only the current assigned driver can acknowledge this exact packet.",
            status=403,
        )
    required = {
        i.carry_method
        for i in db.scalars(select(PacketItem).where(PacketItem.packet_id == packet.id))
    }
    if set(payload.carry_methods) != required:
        fail("REQUIRED_EVIDENCE_MISSING", "Confirm all and only the selected carry methods.")
    row = PacketAck(
        packet_id=packet.id,
        packet_hash=packet.packet_hash,
        assignment_id=assignment.id,
        possession_confirmed=True,
        carry_methods_json=payload.carry_methods,
        note=payload.note,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "DISPATCH_PACKET_ACKNOWLEDGED", row, trade.id)
    return view(row)


def issue(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "dispatch.authorisation.request", lock=True)
    from app.corridor.service import guard

    guard(db, trade, cn)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    evaluation, _, target = ready_evaluation(
        db,
        ctx,
        str(payload.evaluation_id),
        payload.evaluation_hash,
        payload.action,
        "dispatch.authorisation.request",
    )
    if target.id != cn.id:
        fail("NOT_FOUND", "Evaluation not found.", status=404)
    review = approval(db, evaluation, payload.approval_id)
    packet = exists(db, Packet, payload.packet_id)
    if (
        packet.evaluation_id != evaluation.id
        or packet.packet_hash != payload.packet_hash
        or packet.approval_id != review.id
        or packet.action != payload.action
    ):
        fail("PACKET_STALE", "Packet must bind this exact action, evaluation and approval.")
    packet_current(db, packet, trade, cn)
    ack = exists(db, PacketAck, payload.acknowledgment_id)
    assignment = exists(db, Assignment, cn.active_assignment_id)
    if (
        ack.packet_id != packet.id
        or ack.packet_hash != packet.packet_hash
        or ack.assignment_id != assignment.id
        or ack.created_by_user_id != assignment.driver_user_id
    ):
        fail("PACKET_NOT_ACKNOWLEDGED", "Assigned driver must acknowledge this exact packet.")
    expected = "NOT_STARTED" if payload.action == "PICKUP_CONFIRMED" else "PICKED_UP"
    if (
        cn.movement_status != expected
        or cn.planning_status != "PREPARING"
        or cn.revision_alignment != "CURRENT"
    ):
        fail("COMPLIANCE_NOT_READY", "Movement/planning state is not eligible for this action.")
    at = instant(db)
    windows = [
        aware(evaluation.valid_until),
        aware(review.valid_until),
        aware(packet.valid_until),
        aware(assignment.booking_end_at),
    ]
    from .review_authority import windows as reviewer_windows

    windows += reviewer_windows(db, evaluation, trade, cn)
    packet_expiry = live_grant(
        db,
        packet.created_by_user_id,
        packet.prepared_by_organisation_id,
        trade.id,
        "dispatch.packet.prepare",
    )
    ack_expiry = live_grant(
        db,
        assignment.driver_user_id,
        assignment.carrier_organization_id,
        trade.id,
        "dispatch.packet.acknowledge",
    )
    windows += [value for value in (packet_expiry, ack_expiry) if value]
    expiry = live_grant(db, ctx.user.id, ctx.org_id, trade.id, "dispatch.authorisation.request")
    if expiry:
        windows.append(expiry)
    driver_expiry = live_grant(
        db,
        assignment.driver_user_id,
        assignment.carrier_organization_id,
        trade.id,
        "shipment.event.record",
    )
    if driver_expiry:
        windows.append(driver_expiry)
    reviewer_expiry = live_grant(
        db,
        review.created_by_user_id,
        review.reviewer_organisation_id,
        trade.id,
        "dispatch.release.approve",
    )
    if reviewer_expiry:
        windows.append(reviewer_expiry)
    from .models import Fact
    from .observations import timestamp

    binding = exists(db, Binding, evaluation.binding_revision_id)
    fact = exists(db, Fact, binding.fact_revision_id)
    requested = timestamp(
        fact.facts_json.get(
            "requested_pickup_at"
            if payload.action == "PICKUP_CONFIRMED"
            else "requested_departure_at"
        )
    )
    action_start = at
    if payload.action == "PICKUP_CONFIRMED":
        action_start = timestamp(cn.plan_json.get("planned_pickup_start")) or at
        action_end = timestamp(cn.plan_json.get("planned_pickup_end"))
        if action_end:
            windows.append(action_end)
    row = Authorization(
        issued_by_organisation_id=ctx.org_id,
        trade_id=trade.id,
        consignment_id=cn.id,
        action=payload.action,
        execution_mode=trade.execution_mode,
        assignment_id=assignment.id,
        expected_movement_status=expected,
        evaluation_id=evaluation.id,
        evaluation_hash=evaluation.evaluation_hash,
        dependency_hash=evaluation.dependency_hash,
        context_version=context.version(db, trade.id),
        registry_epoch_manifest=evaluation.registry_manifest_json,
        approval_id=review.id,
        packet_id=packet.id,
        packet_hash=packet.packet_hash,
        acknowledgment_id=ack.id,
        loading_manifest_revision_id=evaluation.loading_manifest_revision_id,
        issued_at=at,
        valid_from=max(at, aware(assignment.booking_start_at), requested or at, action_start),
        expires_at=min(windows),
        created_by_user_id=ctx.user.id,
    )
    if row.expires_at <= row.valid_from:
        fail(
            "AUTHORISATION_EXPIRED",
            "No common authorisation/evidence/assignment validity window remains.",
        )
    db.add(row)
    record(db, ctx, "DISPATCH_AUTHORISATION_ISSUED", row)
    db.add(
        AuthorizationEvent(
            authorisation_id=row.id,
            event_type="ISSUED",
            reason="Exact reviewed evaluation and acknowledged dispatch packet",
            evidence_hash=digest({"evaluation": row.evaluation_hash, "packet": row.packet_hash}),
            created_by_user_id=ctx.user.id,
        )
    )
    head = context.heads(db, cn, True)
    setattr(
        head,
        "pickup_authorization_id"
        if payload.action == "PICKUP_CONFIRMED"
        else "departure_authorization_id",
        row.id,
    )
    return read(db, ctx, row.id)


def validate(db, row, trade, cn):
    from app.corridor.service import guard

    at = instant(db)
    if row.consumed_event_id:
        fail("AUTHORISATION_CONSUMED", "Authorisation was already consumed.")
    if row.revoked_at:
        fail("AUTHORISATION_REVOKED", "Authorisation was revoked.")
    if row.execution_mode != trade.execution_mode:
        fail("AUTHORISATION_MODE_MISMATCH", "Authorisation belongs to a different execution mode.")
    if cn.active_assignment_id != row.assignment_id:
        fail("ASSIGNMENT_CHANGED", "Accepted assignment changed.")
    if at < aware(row.valid_from) or at >= aware(row.expires_at):
        fail("AUTHORISATION_EXPIRED", "Authorisation is outside its server-time validity window.")
    if cn.movement_status != row.expected_movement_status:
        fail("COMPLIANCE_NOT_READY", "Movement state changed.")
    guard(db, trade, cn)
    evaluation = exists(db, Evaluation, row.evaluation_id)
    if evaluations.current(db, evaluation, trade, cn, at) != "CURRENT":
        fail("EVALUATION_STALE", "Exact compliance dependencies changed.", status=412)
    approval(db, evaluation, row.approval_id)
    packet_current(db, exists(db, Packet, row.packet_id), trade, cn)
    from .review_authority import windows as reviewer_windows

    reviewer_windows(db, evaluation, trade, cn)
    user = exists(db, User, row.created_by_user_id)
    # The issuance actor remains authorised in the original party/carrier context.
    live_grant(
        db, user.id, row.issued_by_organisation_id, trade.id, "dispatch.authorisation.request"
    )
    assignment = exists(db, Assignment, row.assignment_id)
    live_grant(
        db,
        assignment.driver_user_id,
        assignment.carrier_organization_id,
        trade.id,
        "dispatch.packet.acknowledge",
    )


def consume(db, ctx, trade, cn, assignment, payload, event):
    event_id = event.id
    if not payload.dispatch_authorization_id:
        fail(
            "COMPLIANCE_NOT_READY",
            "A Phase 4 platform dispatch authorisation is required in both execution modes.",
        )
    row = db.scalar(
        select(Authorization)
        .where(Authorization.id == str(payload.dispatch_authorization_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or row.consignment_id != cn.id:
        fail("NOT_FOUND", "Authorisation not found.", status=404)
    if row.action != payload.event_type:
        fail(
            "AUTHORISATION_ACTION_MISMATCH", "Use an authorisation issued for this movement action."
        )
    validate(db, row, trade, cn)
    live_grant(db, ctx.user.id, ctx.org_id, trade.id, "shipment.event.record")
    if payload.event_type == "PICKUP_CONFIRMED":
        manifest = exists(db, Manifest, row.loading_manifest_revision_id)
        if str(payload.loading_manifest_revision_id) != manifest.id:
            fail("LOADING_MANIFEST_MISMATCH", "Pickup must pin the prepared manifest revision.")
        expected = manifest.manifest_json
        actual = payload.payload
        if (
            Decimal(expected["actual_prepared_gross_weight_kg"]) != actual.actual_gross_weight_kg
            or expected["actual_prepared_package_count"] != actual.actual_package_count
        ):
            fail(
                "LOADING_MANIFEST_MISMATCH",
                "Actual pickup weight/package count must match the prepared manifest.",
            )
        by_id = {item["consignment_item_id"]: item for item in expected["items"]}
        if set(by_id) != {str(i.consignment_item_id) for i in actual.items} or any(
            Decimal(by_id[str(i.consignment_item_id)]["loaded_quantity"]) != i.loaded_quantity
            or by_id[str(i.consignment_item_id)]["uqc"] != i.uqc
            for i in actual.items
        ):
            fail(
                "LOADING_MANIFEST_MISMATCH", "Pickup quantities/UQC must match the pinned manifest."
            )
    db.add(event)
    db.flush()
    row.consumed_event_id = event_id
    db.add(
        AuthorizationEvent(
            authorisation_id=row.id,
            event_type="CONSUMED",
            movement_event_id=event_id,
            reason="Atomically consumed by the existing shipment event command",
            evidence_hash=digest({"evaluation": row.evaluation_hash, "packet": row.packet_hash}),
            created_by_user_id=ctx.user.id,
        )
    )
    binding = exists(db, Binding, exists(db, Evaluation, row.evaluation_id).binding_revision_id)
    reservation = db.get(Reservation, binding.binding_json.get("reservation_id"))
    if reservation and not reservation.first_consumed_movement_event_id:
        reservation.first_consumed_movement_event_id = event_id
        db.add(
            ReservationEvent(
                reservation_id=reservation.id,
                event_type="CONSUMED",
                reason="Movement invoice consumed by pickup",
                movement_event_id=event_id,
                created_by_user_id=ctx.user.id,
            )
        )
    record(db, ctx, "DISPATCH_AUTHORISATION_CONSUMED", row)
    from .projection import enqueue

    enqueue(db, ctx, row, event)


def read(db, ctx, ident):
    row = exists(db, Authorization, ident)
    trade, cn, _ = context.access(db, ctx, row.consignment_id)
    body = view(row)
    try:
        validate(db, row, trade, cn)
        body["effective_state"] = "ACTIVE"
    except Exception as exc:
        from app.trades.errors import TradeError

        if not isinstance(exc, TradeError):
            raise
        body["effective_state"] = exc.code
    body["authorisation_id"] = row.id
    return body


def revoke(db, ctx, ident, payload):
    row = exists(db, Authorization, ident)
    context.access(db, ctx, row.consignment_id, "dispatch.authorisation.revoke", lock=True)
    if row.consumed_event_id or row.revoked_at:
        fail("AUTHORISATION_CONSUMED", "Consumed/revoked authorisations cannot be changed.")
    row.revoked_at, row.revocation_reason = instant(db), payload.reason
    db.add(
        AuthorizationEvent(
            authorisation_id=row.id,
            event_type="REVOKED",
            reason=payload.reason,
            evidence_hash=digest({"evaluation": row.evaluation_hash, "packet": row.packet_hash}),
            created_by_user_id=ctx.user.id,
        )
    )
    record(db, ctx, "DISPATCH_AUTHORISATION_REVOKED", row)
    return read(db, ctx, row.id)
