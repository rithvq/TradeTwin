"""Byte-preserving encrypted operational evidence, authorized by Shipments."""

import base64
import hashlib
import json
import os
import socket
import struct
import time
from contextlib import contextmanager
from uuid import UUID

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from minio.error import S3Error
from sqlalchemy import text
from tradetwin_security import identity, service_headers

from app.database import engine
from app.encryption import seal, unseal

router = APIRouter(prefix="/operational-evidence", tags=["Operational evidence (no OCR)"])


def authorize(request, ident, upload=False):
    url = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8011").rstrip("/")
    org = request.headers.get("X-Organization-Id", "")
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                f"{url}/api/v1/operational-attachments/{ident}",
                params={"intent": "upload" if upload else "read"},
                headers={**service_headers(), "X-Organization-Id": org},
            )
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "Evidence access unavailable")
        row = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Evidence authorization unavailable") from exc
    return row, f"operations/{row['trade_id']}/{ident}.enc"


def signature(content, mime):
    if mime == "application/json":
        try:
            from app.document_processing.structured import lossless_json

            data = lossless_json(content)
            return isinstance(data, dict) and (
                data.get("schema_version") in {"PH3_CANONICAL_V1", "PH4_CANONICAL_V2"}
                or any(isinstance(data.get(k), str) for k in ("SignedInvoice", "SignedQRCode"))
                or (
                    isinstance(data.get("DocDtls"), dict) and isinstance(data.get("ItemList"), list)
                )
            )
        except (ValueError, UnicodeError):
            return False
    return {
        "application/pdf": content.startswith(b"%PDF-"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
    }.get(mime, False)


def scan(content):
    host = os.getenv("EVIDENCE_CLAMAV_HOST")
    if not host:
        return "QUARANTINED", "Malware scanner is not configured."
    try:
        with socket.create_connection(
            (host, int(os.getenv("EVIDENCE_CLAMAV_PORT", "3310"))), timeout=15
        ) as client:
            client.sendall(b"zINSTREAM\0")
            for start in range(0, len(content), 65536):
                chunk = content[start : start + 65536]
                client.sendall(struct.pack("!I", len(chunk)) + chunk)
            client.sendall(struct.pack("!I", 0))
            answer = b""
            while len(answer) < 4096 and not answer.endswith(b"\0"):
                part = client.recv(4096)
                if not part:
                    break
                answer += part
        if answer == b"stream: OK\0":
            return "CLEAN", "Malware scan completed; authenticity not assessed."
        if b" FOUND" in answer:
            return "REJECTED", "Malware scanner rejected the file."
    except (OSError, ValueError):
        pass
    return "QUARANTINED", "Malware scanning unavailable or inconclusive."


def plaintext(storage, key):
    return unseal(storage.stored_bytes(key), f"document-object|{key}")


@contextmanager
def upload_lock(ident):
    # Serialize writers across processes before checking the immutable object.
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                lock_id = int.from_bytes(
                    hashlib.sha256(str(ident).encode()).digest()[:8], "big", signed=True
                )
                connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})
            else:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield


def store_original(storage, key, content):
    try:
        previous = plaintext(storage, key)
    except FileNotFoundError:
        previous = None
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            raise
        previous = None
    if previous is None:
        storage.put_bytes(key, seal(content, f"document-object|{key}"))
    elif previous != content:
        raise HTTPException(409, "Original evidence bytes cannot be replaced")


@router.put("/{ident}/content")
async def upload(ident: UUID, request: Request, file: UploadFile = File(...)):
    row, key = authorize(request, str(ident), True)
    if not request.headers.get("Idempotency-Key"):
        raise HTTPException(400, "Idempotency-Key is required")
    content = await file.read(20 * 1024 * 1024 + 1)
    if (
        len(content) != row["size_bytes"]
        or len(content) > 20 * 1024 * 1024
        or not signature(content, row["content_type"])
    ):
        raise HTTPException(422, "File signature or size does not match declared evidence")
    storage = request.app.state.storage
    with upload_lock(ident):
        store_original(storage, key, content)
    return {
        "id": str(ident),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "execution_mode": row["execution_mode"],
    }


@router.get("/{ident}/inspection")
def inspection(ident: UUID, request: Request):
    row, key = authorize(request, str(ident), True)
    content = plaintext(request.app.state.storage, key)
    security, note = (
        scan(content)
        if signature(content, row["content_type"])
        else ("REJECTED", "Invalid file signature")
    )
    return {
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "security_state": security,
        "scanner_note": note,
        "execution_mode": row["execution_mode"],
    }


@router.post("/{ident}/download-authorization")
def download_authorization(ident: UUID, request: Request):
    row, _ = authorize(request, str(ident))
    if row["security_state"] != "CLEAN":
        raise HTTPException(403, "Evidence is quarantined")
    expires = int(time.time()) + 60
    data = {
        "id": str(ident),
        "org": request.headers.get("X-Organization-Id"),
        "user": (identity.get() or {}).get("id"),
        "expires": expires,
    }
    token = base64.urlsafe_b64encode(
        seal(json.dumps(data).encode(), "operational-download")
    ).decode()
    return {
        "url": f"/api/services/document/operational-evidence/{ident}/download?token={token}",
        "expires_at_epoch": expires,
        "execution_mode": row["execution_mode"],
    }


@router.get("/{ident}/download")
def download(ident: UUID, request: Request, token: str):
    try:
        data = json.loads(unseal(base64.urlsafe_b64decode(token), "operational-download"))
    except Exception as exc:
        raise HTTPException(403, "Invalid download authorization") from exc
    if (
        data.get("id") != str(ident)
        or data.get("org") != request.headers.get("X-Organization-Id")
        or data.get("user") != (identity.get() or {}).get("id")
        or data.get("expires", 0) < time.time()
    ):
        raise HTTPException(403, "Download authorization expired or belongs to another profile")
    row, key = authorize(request, str(ident))
    if row["security_state"] != "CLEAN":
        raise HTTPException(403, "Evidence is unavailable")
    content = plaintext(request.app.state.storage, key)
    if hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise HTTPException(503, "Evidence integrity check failed")
    return Response(
        content,
        media_type=row["content_type"],
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="operational-evidence"',
        },
    )
