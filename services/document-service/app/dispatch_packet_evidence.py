"""Narrow authenticated packet grants, re-authorized again when bytes are downloaded."""

import base64
import hashlib
import json
import os
import time
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from tradetwin_security import identity, service_headers

from app.encryption import seal, unseal
from app.operational_evidence import plaintext

router = APIRouter(prefix="/dispatch-packet-evidence", tags=["Guarded dispatch packet evidence"])


def authorize(request, packet_id, item_id):
    base = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8011").rstrip("/")
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                f"{base}/api/v1/dispatch-packets/{packet_id}/items/{item_id}/storage-descriptor",
                headers={
                    **service_headers(),
                    "X-Organization-Id": request.headers.get("X-Organization-Id", ""),
                },
            )
        if response.status_code != 200:
            raise HTTPException(response.status_code, "Current packet access unavailable")
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Packet authorization unavailable") from exc


@router.post("/{packet_id}/{item_id}/download-authorization")
def grant(packet_id: UUID, item_id: UUID, request: Request):
    data = authorize(request, packet_id, item_id)
    payload = {
        "packet_id": str(packet_id),
        "item_id": str(item_id),
        "user": (identity.get() or {}).get("id"),
        "org": request.headers.get("X-Organization-Id"),
        "expires": int(time.time()) + 60,
        "source_hash": data["sha256"],
    }
    token = base64.urlsafe_b64encode(
        seal(json.dumps(payload).encode(), "dispatch-packet-download")
    ).decode()
    return {
        "url": (
            f"/api/services/document/dispatch-packet-evidence/{packet_id}/"
            f"{item_id}/download?token={token}"
        ),
        "expires_at_epoch": payload["expires"],
        "execution_mode": data["execution_mode"],
    }


@router.get("/{packet_id}/{item_id}/download")
def download(packet_id: UUID, item_id: UUID, request: Request, token: str):
    try:
        value = json.loads(unseal(base64.urlsafe_b64decode(token), "dispatch-packet-download"))
    except Exception as exc:
        raise HTTPException(403, "Invalid packet download grant") from exc
    if (
        value.get("packet_id") != str(packet_id)
        or value.get("item_id") != str(item_id)
        or value.get("user") != (identity.get() or {}).get("id")
        or value.get("org") != request.headers.get("X-Organization-Id")
        or time.time() >= value.get("expires", 0)
    ):
        raise HTTPException(403, "Packet grant expired or belongs to another identity")
    data = authorize(request, packet_id, item_id)
    if value["source_hash"] != data["sha256"]:
        raise HTTPException(403, "Packet source changed")
    content = plaintext(request.app.state.storage, data["storage_key"])
    if hashlib.sha256(content).hexdigest() != data["sha256"]:
        raise HTTPException(503, "Packet representation integrity failed")
    return Response(
        content,
        media_type=data["content_type"],
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="dispatch-evidence"',
        },
    )
