"""Packet-specific access never grants a driver general access to financial originals."""

import os

import httpx
from sqlalchemy import select
from tradetwin_security import service_headers

from app.document_desk.models import Artifact, Asset
from app.operations.access import exists, fail
from app.operations.models import Assignment, Attachment

from . import context, dispatch
from .models import Packet, PacketItem


def descriptor(db, ctx, packet_id, item_id, lock=True):
    packet, item = exists(db, Packet, packet_id), exists(db, PacketItem, item_id)
    trade, cn, side = context.access(
        db, ctx, packet.consignment_id, "dispatch.packet.read", lock=lock
    )
    dispatch.packet_current(db, packet, trade, cn)
    if item.packet_id != packet.id:
        fail("NOT_FOUND", "Packet item not found.", status=404)
    assignment = exists(db, Assignment, packet.assignment_id)
    if side != "SELLER" and (
        ctx.user.id != assignment.driver_user_id or ctx.user.id != item.allowed_recipient_user_id
    ):
        fail(
            "FORBIDDEN",
            "This packet representation is limited to the seller and current assigned driver.",
            status=403,
        )
    dispatch.live_grant(db, ctx.user.id, ctx.org_id, trade.id, "dispatch.packet.read")
    if item.artifact_id:
        artifact = exists(db, Artifact, item.artifact_id)
        if (
            artifact.document_version_id != item.document_version_id
            or artifact.artifact_type != "SIGNED_QR_IMAGE"
            or artifact.content_type != "image/png"
            or artifact.sha256 != item.source_sha256
        ):
            fail("PACKET_STALE", "Derived representation changed.", status=412)
        return {
            "packet_id": packet.id,
            "item_id": item.id,
            "trade_id": trade.id,
            "storage_key": artifact.object_key,
            "sha256": artifact.sha256,
            "content_type": artifact.content_type,
            "execution_mode": packet.execution_mode,
        }
    attachment_id = item.source_reference_json.get("attachment_id")
    if not attachment_id:
        fail(
            "UNSUPPORTED_SCOPE",
            "This reference/number is carried as a manifest entry, not a downloadable original.",
        )
    attachment = exists(db, Attachment, attachment_id)
    asset = db.scalar(
        select(Asset).where(
            Asset.attachment_id == attachment.id,
            Asset.document_version_id == item.document_version_id,
        )
    )
    if not asset or attachment.security_state != "CLEAN" or attachment.sha256 != item.source_sha256:
        fail(
            "PACKET_STALE",
            "Source representation no longer matches clean packet evidence.",
            status=412,
        )
    return {
        "packet_id": packet.id,
        "item_id": item.id,
        "trade_id": trade.id,
        "storage_key": f"operations/{trade.id}/{attachment.id}.enc",
        "sha256": attachment.sha256,
        "content_type": attachment.content_type,
        "execution_mode": packet.execution_mode,
    }


def download(db, ctx, packet_id, item_id):
    # Storage rechecks through its own descriptor callback; never hold a trade lock across HTTP.
    descriptor(db, ctx, packet_id, item_id, lock=False)
    base = os.getenv("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8013").rstrip("/")
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(
                f"{base}/dispatch-packet-evidence/{packet_id}/{item_id}/download-authorization",
                headers={**service_headers(), "X-Organization-Id": ctx.org_id},
            )
        if response.status_code != 200:
            fail("EVIDENCE_UNAVAILABLE", "Packet storage authorization unavailable.", status=503)
        return response.json()
    except httpx.HTTPError:
        fail("EVIDENCE_UNAVAILABLE", "Encrypted storage unavailable.", status=503)
