from sqlalchemy import func, select

from app.operations import attachments
from app.operations.access import consignment, exists, fail
from app.operations.models import Assignment, Attachment, Consignment, Dispute, Payment, Receipt
from app.trades.models import uid
from app.trades.terms import digest

from . import access
from .ledger import match, record, result, touch
from .models import AccessGrant, Asset, Document, Relationship, SubjectLink, Version


def add_version(db, ctx, doc, payload, initial=False):
    if not initial:
        access.document(db, ctx, doc.id, "document.version.add", True)
        match(ctx, doc, "SOURCE_VERSION_CHANGED")
    values = [(str(payload.primary_attachment_id), "PRIMARY")] + [
        (str(a.attachment_id), a.role) for a in payload.supporting_assets
    ]
    if len({i for i, _ in values}) != len(values):
        fail("VALIDATION_ERROR", "A source asset cannot be included twice.", status=422)
    assets = []
    for ident, role in values:
        row = exists(db, Attachment, ident)
        attachments.access(db, ctx, row)
        if row.trade_id != doc.trade_id:
            fail("NOT_FOUND", "Source asset not found.", status=404)
        if not row.finalised_at or row.security_state != "CLEAN" or not row.sha256:
            fail("ATTACHMENT_NOT_CLEAN", "Finalise and scan every asset before registration.")
        if (
            row.content_type == "application/json"
            and doc.document_type != "SIGNED_EINVOICE_JSON"
            and role != "SIGNED_PAYLOAD"
        ):
            fail(
                "UNSUPPORTED_DOCUMENT_TYPE",
                "JSON is supported only for structured e-invoice payloads.",
                status=422,
            )
        assets.append((row, role))
    number = (
        db.scalar(select(func.max(Version.version_number)).where(Version.document_id == doc.id))
        or 0
    ) + 1
    version = Version(
        id=uid(),
        document_id=doc.id,
        version_number=number,
        reason="INITIAL" if initial else payload.reason,
        reason_text="Initial registered source" if initial else payload.reason_text,
        supersedes_version_id=doc.current_version_id,
        source_manifest_hash=digest(
            [{"attachment_id": a.id, "sha256": a.sha256, "role": role} for a, role in assets]
        ),
        created_by_user_id=ctx.user.id,
        created_by_organization_id=ctx.org_id,
    )
    db.add(version)
    db.flush()
    for a, role in assets:
        db.add(
            Asset(
                document_version_id=version.id, attachment_id=a.id, role=role, asset_sha256=a.sha256
            )
        )
    if doc.current_version_id:
        for link in db.scalars(
            select(SubjectLink).where(
                SubjectLink.document_version_id == doc.current_version_id,
                SubjectLink.revoked_at.is_(None),
            )
        ):
            db.add(
                SubjectLink(
                    document_version_id=version.id,
                    subject_type=link.subject_type,
                    subject_id=link.subject_id,
                    created_by_user_id=ctx.user.id,
                )
            )
    doc.current_version_id = version.id
    doc.latest_draft_fact_revision_id = None
    doc.effective_fact_revision_id = None
    doc.current_mapping_revision_id = None
    touch(doc)
    record(
        db,
        ctx,
        "DOCUMENT_SOURCE_REGISTERED" if initial else "DOCUMENT_SOURCE_REPLACED",
        doc,
        version,
        {"source_manifest_hash": version.source_manifest_hash, "invalidated_review": not initial},
    )
    return version


def create(db, ctx, trade_id, payload):
    if str(payload.trade_id) != str(trade_id):
        fail("VALIDATION_ERROR", "Registration trade does not match the URL.", status=422)
    trade = access.registration_access(
        db, ctx, trade_id, payload.document_type, payload.initial_consignment_id
    )
    values = payload.model_dump(
        exclude={"trade_id", "initial_consignment_id", "primary_attachment_id", "supporting_assets"}
    )
    if values["declared_issuer_organization_id"]:
        if (
            not access.recipient(
                db,
                type("Doc", (), {"trade_id": trade.id})(),
                values["declared_issuer_organization_id"],
            )
            and str(values["declared_issuer_organization_id"]) != ctx.org_id
        ):
            fail("VALIDATION_ERROR", "Issuer organisation is unknown.", status=422)
        values["declared_issuer_organization_id"] = str(values["declared_issuer_organization_id"])
    doc = Document(
        id=uid(),
        trade_id=trade.id,
        owner_organization_id=ctx.org_id,
        execution_mode=trade.execution_mode,
        created_by=ctx.user.id,
        **values,
    )
    db.add(doc)
    db.flush()
    version = add_version(db, ctx, doc, payload, True)
    db.add(
        SubjectLink(
            document_version_id=version.id,
            subject_type="TRADE",
            subject_id=trade.id,
            created_by_user_id=ctx.user.id,
        )
    )
    if payload.initial_consignment_id:
        link_subject(
            db,
            ctx,
            version.id,
            type(
                "Subject",
                (),
                {
                    "subject_type": "CONSIGNMENT",
                    "subject_id": payload.initial_consignment_id,
                },
            )(),
        )
    from .views import document_view

    return document_view(db, ctx, doc)


def version_add(db, ctx, ident, payload):
    doc, _ = access.document(db, ctx, ident, "document.version.add", True)
    add_version(db, ctx, doc, payload)
    from .views import document_view

    return document_view(db, ctx, doc)


def archive(db, ctx, ident, payload):
    doc, _ = access.document(db, ctx, ident, "document.archive", True)
    match(ctx, doc)
    doc.lifecycle_status = "ARCHIVED"
    touch(doc)
    record(
        db,
        ctx,
        "DOCUMENT_ARCHIVED",
        doc,
        detail={"reason": payload.reason, "government_cancellation": False},
    )
    return result(doc)


def relationship(db, ctx, ident, payload):
    doc, _ = access.document(db, ctx, ident, "document.review.submit", True)
    other, _ = access.document(db, ctx, payload.to_document_id, "document.read")
    match(ctx, doc)
    if other.trade_id != doc.trade_id or other.id == doc.id:
        fail("VALIDATION_ERROR", "Link distinct documents within the same trade.", status=422)
    if payload.relationship_type == "DUPLICATE_PRESENTATION_OF":
        if not doc.effective_fact_revision_id or not other.effective_fact_revision_id:
            fail(
                "DUPLICATE_CANONICAL_REVIEW_REQUIRED",
                "Review both presentations before selecting a canonical record.",
            )
        compatible = (
            doc.document_type == other.document_type
            or {doc.document_type, other.document_type} <= access.INVOICE_PRESENTATIONS
        )
        if other.canonical_document_id or not compatible:
            fail(
                "DUPLICATE_CANONICAL_REVIEW_REQUIRED",
                "Select a non-alias canonical presentation of the same type.",
            )
        if doc.current_mapping_revision_id:
            doc.current_mapping_revision_id = None
        doc.canonical_document_id = other.id
    row = Relationship(
        from_document_id=doc.id,
        to_document_id=other.id,
        relationship_type=payload.relationship_type,
        reason=payload.reason,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(row)
    touch(doc)
    record(
        db,
        ctx,
        "DOCUMENT_RELATIONSHIP_RECORDED",
        doc,
        detail={"relationship": payload.relationship_type, "target_id": other.id},
    )
    return result(row, doc)


def link_subject(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.register", True)
    model = {
        "CONSIGNMENT": Consignment,
        "RECEIPT": Receipt,
        "PAYMENT": Payment,
        "DISPUTE": Dispute,
    }.get(payload.subject_type)
    if model:
        row = exists(db, model, payload.subject_id)
        if payload.subject_type == "RECEIPT":
            _, cn, _ = consignment(db, ctx, row.consignment_id)
            trade_id = cn.trade_id
        else:
            trade_id = row.trade_id
        if trade_id != doc.trade_id:
            fail("NOT_FOUND", "Subject not found.", status=404)
        if payload.subject_type == "CONSIGNMENT":
            consignment(db, ctx, row.id)
        if payload.subject_type == "PAYMENT" and doc.document_type != "PAYMENT_EVIDENCE":
            fail("FORBIDDEN", "Payment links require a finance-restricted document.", status=403)
    elif str(payload.subject_id) != doc.trade_id:
        fail("NOT_FOUND", "Trade not found.", status=404)
    row = SubjectLink(
        document_version_id=version.id,
        subject_type=payload.subject_type,
        subject_id=str(payload.subject_id),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(
        db,
        ctx,
        "DOCUMENT_SUBJECT_LINKED",
        doc,
        version,
        {"subject_type": row.subject_type, "subject_id": row.subject_id},
    )
    return result(row, doc)


def share(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.share", True)
    assignment = db.get(Assignment, str(payload.assignment_id)) if payload.assignment_id else None
    if payload.access_type == "OPERATIONAL_PROJECTION":
        if doc.document_type not in access.OPERATIONAL or not assignment:
            fail("FORBIDDEN", "Only operational documents have carrier projections.", status=403)
        cn = db.get(Consignment, assignment.consignment_id)
        if cn.trade_id != doc.trade_id or assignment.carrier_organization_id != str(
            payload.grantee_organization_id
        ):
            fail("NOT_FOUND", "Assignment not found.", status=404)
        if assignment.status != "ACCEPTED" or cn.active_assignment_id != assignment.id:
            fail("FORBIDDEN", "Projection needs the current accepted assignment.", status=403)
        if (
            not payload.allowed_field_paths
            or not set(payload.allowed_field_paths) <= access.OPERATIONAL_PATHS
        ):
            fail(
                "FORBIDDEN", "Only server-allowlisted operational fields can be shared.", status=403
            )
    elif not access.recipient(db, doc, payload.grantee_organization_id):
        fail("FORBIDDEN", "Original/reviewed sharing is limited to trade parties.", status=403)
    row = AccessGrant(
        document_version_id=version.id,
        grantee_organization_id=str(payload.grantee_organization_id),
        access_type=payload.access_type,
        assignment_id=str(payload.assignment_id) if payload.assignment_id else None,
        allowed_field_paths_json=payload.allowed_field_paths,
        granted_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(
        db,
        ctx,
        "DOCUMENT_ACCESS_GRANTED",
        doc,
        version,
        {"access_type": row.access_type, "recipient_id": row.grantee_organization_id},
    )
    return result(row, doc)


def revoke(db, ctx, model, ident, payload):
    from app.trades.models import now

    row = exists(db, model, ident)
    version, doc, _ = access.version(db, ctx, row.document_version_id, "document.share", True)
    row.revoked_at = now()
    record(
        db,
        ctx,
        "DOCUMENT_ACCESS_REVOKED" if model is AccessGrant else "DOCUMENT_LINK_REVOKED",
        doc,
        version,
        {"record_id": row.id, "reason": payload.reason},
    )
    return result(row, doc)
