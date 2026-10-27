"""Opt-in signed development import; uses normal encrypted storage and scanning."""

import base64
import hashlib
import os
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from tradetwin_security.document_worker import headers

from app.operational_evidence import scan, signature, store_original, upload_lock

router = APIRouter(tags=["Internal simulation fixtures"])


class GeneratedFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID
    user_id: UUID
    organization_id: UUID
    content_base64: str = Field(max_length=4_000_000)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/internal/document-desk/import-generated-fixture", include_in_schema=False)
def import_generated(payload: GeneratedFixture, request: Request):
    if not any(
        os.getenv(flag, "false").lower() == "true"
        for flag in ("DOCUMENT_DEMO_ENABLED", "IN_APP_DEMO_ENABLED")
    ):
        raise HTTPException(404, "Development fixture import is disabled")
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(422, "Invalid development fixture") from exc
    actual = hashlib.sha256(content).hexdigest()
    if actual != payload.expected_sha256:
        raise HTTPException(422, "Fixture hash mismatch")
    url = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8011").rstrip("/")
    with httpx.Client(timeout=15) as client:
        response = client.post(
            f"{url}/internal/document-desk/fixture-input",
            headers=headers(),
            json={
                "attachment_id": str(payload.attachment_id),
                "user_id": str(payload.user_id),
                "organization_id": str(payload.organization_id),
                "fixture_name": "phase4.pdf",
            },
        )
    if response.status_code != 200:
        raise HTTPException(response.status_code, "Simulation fixture access denied")
    row = response.json()
    if (
        row["execution_mode"] != "SIMULATION"
        or len(content) != row["size_bytes"]
        or not signature(content, row["content_type"])
    ):
        raise HTTPException(422, "Fixture scope, signature or size mismatch")
    key = f"operations/{row['trade_id']}/{row['id']}.enc"
    with upload_lock(row["id"]):
        store_original(request.app.state.storage, key, content)
    state, note = scan(content)
    return {"sha256": actual, "security_state": state, "scanner_note": note}
