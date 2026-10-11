"""Shipment owns authorization/metadata; Documents owns encrypted bytes and scanning."""

import os

import httpx
from tradetwin_security import service_headers

from app.trades.models import now, uid

from .access import consignment, exists, fail, has, party
from .ledger import record, view
from .models import Attachment, AttachmentLink


def access(db, ctx, row, upload=False):
    if row.consignment_id:
        trade, cn, side = consignment(
            db, ctx, row.consignment_id, "attachment.upload" if upload else "consignment.read"
        )
    else:
        trade, side = party(
            db, ctx, row.trade_id, "attachment.upload" if upload else "consignment.read"
        )
        cn = None
    if row.purpose == "PAYMENT" and (
        not side
        or not (
            has(db, ctx, "payment.report", trade.id, side)
            or has(db, ctx, "payment.acknowledge", trade.id, side)
        )
    ):
        fail("FORBIDDEN", "Payment evidence requires finance authority.", status=403)
    if upload and (
        row.created_by != ctx.user.id
        or row.uploaded_by_organization_id != ctx.org_id
        or row.security_state != "UPLOADING"
    ):
        fail("FORBIDDEN", "Only the original uploader can complete this upload once.", status=403)
    return trade, cn


def begin(db, ctx, payload):
    trade, _ = (
        party(db, ctx, payload.trade_id, "attachment.upload", lock=True)
        if not payload.consignment_id
        else (consignment(db, ctx, payload.consignment_id, "attachment.upload", lock=True)[0], None)
    )
    cn = None
    if payload.consignment_id:
        _, cn, _ = consignment(db, ctx, payload.consignment_id)
        if cn.trade_id != str(payload.trade_id):
            fail("VALIDATION_ERROR", "Attachment consignment/trade mismatch.", status=422)
    row = Attachment(
        id=uid(),
        trade_id=trade.id,
        consignment_id=cn.id if cn else None,
        purpose=payload.purpose,
        original_name=payload.original_name,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        uploaded_by_organization_id=ctx.org_id,
        created_by=ctx.user.id,
        object_key="",
    )
    row.object_key = f"operations/{trade.id}/{row.id}.enc"
    db.add(row)
    db.flush()
    access(db, ctx, row, True)
    record(db, ctx, "EVIDENCE_UPLOAD_INITIATED", row, trade, cn)
    return {
        **view(row, trade, ctx),
        "upload": {
            "method": "PUT",
            "url": f"/api/services/document/operational-evidence/{row.id}/content",
            "multipart_field": "file",
            "requires_organization_header": True,
        },
    }


def storage_call(ctx, ident, action, method="GET"):
    url = os.getenv("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8013").rstrip("/")
    try:
        with httpx.Client(
            timeout=30, headers={**service_headers(), "X-Organization-Id": ctx.org_id}
        ) as client:
            response = client.request(method, f"{url}/operational-evidence/{ident}/{action}")
        if response.status_code >= 400:
            fail(
                "EVIDENCE_UNAVAILABLE",
                "Evidence storage or scan is unavailable; no clean status was granted.",
                status=503,
            )
        return response.json()
    except httpx.HTTPError as exc:
        from app.trades.errors import TradeError

        raise TradeError(
            "EVIDENCE_UNAVAILABLE", "Encrypted evidence storage is unavailable.", 503
        ) from exc


def complete(db, ctx, ident, payload):
    row = exists(db, Attachment, ident)
    trade, cn = access(db, ctx, row, True)
    checked = storage_call(ctx, row.id, "inspection")
    if checked["size_bytes"] != row.size_bytes or (
        payload.expected_sha256 and checked["sha256"] != payload.expected_sha256
    ):
        fail(
            "VALIDATION_ERROR",
            "Stored size or server hash does not match expected upload.",
            status=422,
        )
    row.sha256, row.security_state, row.finalised_at = (
        checked["sha256"],
        checked["security_state"],
        now(),
    )
    from .ledger import touch

    touch(row)
    record(
        db,
        ctx,
        "EVIDENCE_UPLOAD_COMPLETED",
        row,
        trade,
        cn,
        {"security_state": row.security_state, "authenticity": "NOT_ASSESSED"},
    )
    return {
        **view(row, trade, ctx),
        "authenticity": "NOT_ASSESSED",
        "scanner_note": checked.get("scanner_note"),
    }


def download(db, ctx, ident):
    row = exists(db, Attachment, ident)
    access(db, ctx, row)
    if row.security_state != "CLEAN":
        fail(
            "EVIDENCE_QUARANTINED", "Only clean, authorized evidence can be downloaded.", status=403
        )
    return storage_call(ctx, row.id, "download-authorization", "POST")


def link(db, ctx, trade, cn, subject, identifiers):
    db.flush()
    for ident in set(str(i) for i in identifiers):
        row = exists(db, Attachment, ident)
        access(db, ctx, row)
        if (
            row.trade_id != trade.id
            or (row.consignment_id and (not cn or row.consignment_id != cn.id))
            or row.security_state != "CLEAN"
        ):
            fail(
                "VALIDATION_ERROR",
                "Link only authorized clean evidence from this trade/consignment.",
                "evidence_attachment_ids",
                422,
            )
        db.add(
            AttachmentLink(
                attachment_id=row.id,
                subject_type=type(subject).__name__,
                subject_id=subject.id,
                linked_by_user_id=ctx.user.id,
            )
        )
