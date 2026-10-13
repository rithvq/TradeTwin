import base64
import hashlib
import json
import os
import secrets
import time
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from tradetwin_security import identity, service_headers
from tradetwin_security.document_worker import headers as worker_headers

from app.encryption import seal, unseal
from app.operational_evidence import plaintext, scan, signature, store_original, upload_lock

from .parser import ParseFailure, isolated_parse

router = APIRouter(tags=["Document desk encrypted storage"])


class Lease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    attempt_id: UUID
    lease_token: str


class FixtureImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID
    user_id: UUID
    organization_id: UUID
    fixture_name: str


@router.post("/internal/document-desk/import-fixture")
def import_fixture(payload: FixtureImport, request: Request):
    from pathlib import Path

    if os.getenv("DOCUMENT_DEMO_ENABLED", "false").lower() != "true":
        raise HTTPException(404, "Development fixture import is disabled")
    folder = Path(os.getenv("DOCUMENT_FIXTURE_DIRECTORY", "/app/data/fixtures/document-desk"))
    manifest = json.loads((folder / "manifest.json").read_text())
    name = payload.fixture_name
    if name not in manifest or Path(name).name != name:
        raise HTTPException(422, "Use an allowlisted development fixture")
    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{shipment_url()}/internal/document-desk/fixture-input",
            headers=worker_headers(),
            json=payload.model_dump(mode="json"),
        )
    if response.status_code != 200:
        raise HTTPException(response.status_code, "Development fixture access denied")
    row = response.json()
    content = (folder / name).read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    expected = manifest[name]["sha256"] if isinstance(manifest[name], dict) else manifest[name]
    if (
        actual != expected
        or len(content) != row["size_bytes"]
        or not signature(content, row["content_type"])
    ):
        raise HTTPException(422, "Fixture integrity or declared file type mismatch")
    key = f"operations/{row['trade_id']}/{row['id']}.enc"
    with upload_lock(row["id"]):
        store_original(request.app.state.storage, key, content)
    security, note = scan(content)
    return {
        "sha256": actual,
        "size_bytes": len(content),
        "security_state": security,
        "scanner_note": note,
    }


def shipment_url():
    return os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8011").rstrip("/")


def artifact_key(row):
    return f"derived/{row['document_version_id']}/{row['job_attempt_id']}/{row['id']}.enc"


def store(
    storage,
    version_id,
    attempt_id,
    kind,
    content,
    content_type,
    attachment_id=None,
    metadata=None,
    ident=None,
):
    row = {
        "id": ident or str(uuid4()),
        "document_version_id": version_id,
        "job_attempt_id": attempt_id,
        "source_attachment_id": attachment_id,
        "artifact_type": kind,
        "content_type": content_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "transformation_metadata_json": metadata or {},
    }
    row["object_key"] = artifact_key(row)
    storage.put_bytes(row["object_key"], seal(content, f"document-object|{row['object_key']}"))
    return row


@router.post("/internal/document-desk/process")
def process(payload: Lease, request: Request):
    with httpx.Client(timeout=15) as client:
        response = client.post(
            f"{shipment_url()}/internal/document-desk/input",
            json=payload.model_dump(mode="json"),
            headers=worker_headers(),
        )
    if response.status_code != 200:
        raise HTTPException(response.status_code, "Worker input access unavailable")
    basis = response.json()
    storage = request.app.state.storage
    if basis["stage"] == "VERIFY":
        return verify_input(storage, basis)
    output = {
        "artifacts": [],
        "pages": [],
        "file_metadata": [],
        "observations": [],
        "canonical_document": {},
        "engine_kind": "RULES",
        "engine_name": "TradeTwin capture",
        "engine_version": "PH3_CAPTURE_V1",
        "status": "SUCCEEDED",
    }
    deadline = time.monotonic() + 300
    try:
        for asset in basis["assets"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ParseFailure("STAGE_TIMEOUT")
            key = f"operations/{basis['trade_id']}/{asset['attachment_id']}.enc"
            content = plaintext(storage, key)
            if hashlib.sha256(content).hexdigest() != asset["asset_sha256"]:
                raise ParseFailure("FILE_SIGNATURE_MISMATCH")
            text_id = str(uuid4())
            options = {
                **basis["configuration"],
                "text_artifact_id": text_id,
                "execution_mode": basis["execution_mode"],
                "document_type": basis["document_type"],
                "original_name": asset["original_name"],
                "timeout_seconds": remaining,
            }
            manifest_path = os.getenv("DOCUMENT_SIMULATION_FIXTURES_FILE")
            if manifest_path and basis["execution_mode"] == "SIMULATION":
                from pathlib import Path

                manifest = json.loads(Path(manifest_path).read_text())
                options["simulation_fixture"] = manifest.get(asset["asset_sha256"])
            parsed = isolated_parse(
                content,
                asset["content_type"],
                asset["attachment_id"],
                options,
                basis["request"].get("strategy", "AUTO"),
            )
            output["file_metadata"].append(
                {"attachment_id": asset["attachment_id"], "metadata_json": parsed["metadata"]}
            )
            if parsed["text"]:
                artifact = store(
                    storage,
                    basis["version_id"],
                    basis["attempt_id"],
                    "OCR_TEXT" if parsed["text_method"] == "OCR" else "NATIVE_TEXT",
                    parsed["text"].encode(),
                    "text/plain",
                    asset["attachment_id"],
                    {"character_count": len(parsed["text"]), "method": parsed["text_method"]},
                    text_id,
                )
                output["artifacts"].append(artifact)
            for page in parsed["pages"]:
                artifact = store(
                    storage,
                    basis["version_id"],
                    basis["attempt_id"],
                    "PAGE_IMAGE",
                    base64.b64decode(page.pop("image")),
                    "image/png",
                    asset["attachment_id"],
                    page["transformation_json"],
                )
                output["artifacts"].append(artifact)
                output["pages"].append({**page, "page_image_artifact_id": artifact["id"]})
            for key, token in parsed["signed_tokens"].items():
                output["artifacts"].append(
                    store(
                        storage,
                        basis["version_id"],
                        basis["attempt_id"],
                        "DECODED_SIGNED_PAYLOAD",
                        token.encode(),
                        "text/plain",
                        asset["attachment_id"],
                        {"token_kind": key, "unverified": True},
                    )
                )
            for qr in parsed["qr_payloads"]:
                output["artifacts"].append(
                    store(
                        storage,
                        basis["version_id"],
                        basis["attempt_id"],
                        "DECODED_SIGNED_PAYLOAD",
                        qr["payload"].encode(),
                        "text/plain",
                        asset["attachment_id"],
                        {
                            "token_kind": "QR",
                            "page_number": qr["page_number"],
                            "bounding_box": qr["bounding_box"],
                            "unverified": True,
                        },
                    )
                )
            if asset["role"] == "PRIMARY":
                for k in (
                    "canonical_document",
                    "observations",
                    "engine_kind",
                    "engine_name",
                    "engine_version",
                    "status",
                    "error_code",
                ):
                    if k in parsed:
                        output[k] = parsed[k]
        return output
    except ParseFailure as exc:
        return {"error_code": exc.code, "status": "FAILED"}


def verify_input(storage, basis):
    from datetime import UTC, datetime, timedelta

    from .adapters import ReadOnlyAdapter
    from .signatures import verify
    from .structured import lossless_json

    kind = basis["request"]["check_type"]
    environment = (
        basis.get("connection", {}).get("provider_environment")
        if basis.get("connection")
        else basis["execution_mode"]
    )
    if environment == "PRODUCTION":
        environment = "LIVE"
    instant = datetime.now(UTC)
    result = {
        "check_type": kind,
        "method": "OFFLINE_SIGNATURE",
        "adapter_name": "PH3_LOCAL_CHECKS",
        "adapter_version": "1",
        "provider_environment": environment,
        "input_hash": basis["verification_input_hash"],
        "checked_at": instant.isoformat(),
        "provider_observed_at": None,
        "lookup_outcome": "NOT_CHECKED",
        "signature_integrity": "NOT_CHECKED",
        "issuer_trust": "NOT_CHECKED",
        "certificate_revocation_status": "NOT_CHECKED",
        "identifier_match": "NOT_ASSESSED",
        "authority_returned_status": None,
        "trusted_key_id": None,
        "covered_field_paths": [],
        "normalised_result": {},
        "response_artifact_id": None,
        "request_reference": None,
        "fresh_until": (
            instant + timedelta(seconds=int(os.getenv("DOCUMENT_VERIFICATION_TTL_SECONDS", "3600")))
        ).isoformat(),
        "limitations": ["Document evidence is not dispatch authorisation."],
    }
    artifacts = []
    if kind in {"IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE"}:
        token, attachment_id = None, None
        artifact = basis.get("signed_artifact")
        if artifact:
            token = plaintext(storage, artifact_key(artifact)).decode()
            attachment_id = artifact["source_attachment_id"]
            if hashlib.sha256(token.encode()).hexdigest() != artifact["sha256"]:
                raise HTTPException(503, "Signed artifact integrity check failed")
        else:
            for asset in basis["assets"]:
                if asset["content_type"] == "application/json":
                    raw = plaintext(
                        storage, f"operations/{basis['trade_id']}/{asset['attachment_id']}.enc"
                    )
                    if hashlib.sha256(raw).hexdigest() != asset["asset_sha256"]:
                        raise HTTPException(503, "Signed source integrity check failed")
                    data = lossless_json(raw)
                    token = data.get(
                        "SignedQRCode" if kind == "IRP_QR_SIGNATURE" else "SignedInvoice"
                    )
                    attachment_id = asset["attachment_id"]
                    if token:
                        break
        result.update(
            verify(token, basis["trusted_keys"], environment, attachment_id)
            if token
            else {
                "signature_integrity": "NOT_PRESENT",
                "limitations": ["No supported compact signed payload was found."],
            }
        )
        page = basis.get("signed_page_artifact")
        box = (
            artifact.get("transformation_metadata_json", {}).get("bounding_box")
            if artifact
            else None
        )
        if (
            result["signature_integrity"] == "VALID"
            and result["issuer_trust"] == "TRUSTED_FOR_THIS_CHECK"
            and page
            and box
        ):
            from io import BytesIO

            from PIL import Image

            raw_page = plaintext(storage, artifact_key(page))
            if hashlib.sha256(raw_page).hexdigest() != page["sha256"]:
                raise HTTPException(503, "Verified QR page integrity failed")
            with Image.open(BytesIO(raw_page)) as original:
                if original.width * original.height > 25000000:
                    raise HTTPException(422, "Verified QR page exceeds image limits")
                bounds = (
                    int(box["x0"] * original.width),
                    int(box["y0"] * original.height),
                    int(box["x1"] * original.width),
                    int(box["y1"] * original.height),
                )
                if (
                    not 0 <= bounds[0] < bounds[2] <= original.width
                    or not 0 <= bounds[1] < bounds[3] <= original.height
                ):
                    raise HTTPException(422, "Verified QR bounds are invalid")
                buffer = BytesIO()
                original.crop(bounds).save(buffer, format="PNG")
            image = store(
                storage,
                basis["version_id"],
                basis["attempt_id"],
                "SIGNED_QR_IMAGE",
                buffer.getvalue(),
                "image/png",
                attachment_id,
                {
                    "verification_input_hash": basis["verification_input_hash"],
                    "source_page_sha256": page["sha256"],
                    "signature_checked": True,
                },
            )
            artifacts.append(image)
            result["signed_qr_artifact_id"] = image["id"]
    elif kind == "PDF_SIGNATURE":
        result.update(
            signature_integrity="UNSUPPORTED",
            issuer_trust="UNKNOWN",
            limitations=[
                "PDF byte-range, certificate-chain, and revocation verification "
                "is unsupported by this deployment."
            ],
        )
    elif kind == "GSTIN_FORMAT":
        import re

        identifier = basis.get("target_value")
        valid = bool(
            isinstance(identifier, str)
            and re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", identifier)
        )
        result.update(
            method="LOCAL_FORMAT",
            normalised_result={
                "format_outcome": "PASS" if valid else "UNKNOWN" if identifier is None else "FAIL"
            },
            covered_field_paths=[basis["request"].get("target_field_path")] if identifier else [],
            limitations=[
                "Structural format only; checksum and active registration are not established."
            ],
        )
    else:
        adapter = ReadOnlyAdapter()
        if adapter.validateInput(kind, basis.get("target_value")):
            outcome, normal, raw = adapter.check(
                kind, basis["target_value"], basis.get("connection"), basis["execution_mode"]
            )
        else:
            outcome, normal, raw = (
                "NOT_CONFIGURED" if not basis.get("connection") else "ERROR",
                {},
                None,
            )
        result.update(
            method="AUTHORISED_LOOKUP",
            adapter_name=adapter.name,
            lookup_outcome=outcome,
            normalised_result=normal,
            authority_returned_status=normal.get("status"),
            provider_observed_at=normal.get("provider_observed_at"),
            request_reference=normal.get("request_reference"),
            limitations=adapter.describeLimitations(),
        )
        if outcome == "RESULT_RETURNED":
            result["identifier_match"] = (
                "MATCH" if normal.get("identifier") == basis["target_value"] else "MISMATCH"
            )
        if raw:
            artifact = store(
                storage,
                basis["version_id"],
                basis["attempt_id"],
                "RAW_VERIFICATION",
                raw,
                "application/json",
            )
            artifacts.append(artifact)
            result["response_artifact_id"] = artifact["id"]
    return {"status": "SUCCEEDED", "verification_result": result, "artifacts": artifacts}


def authorize_artifact(request, ident):
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{shipment_url()}/api/v1/document-artifacts/{ident}",
            headers={
                **service_headers(),
                "X-Organization-Id": request.headers.get("X-Organization-Id", ""),
            },
        )
    if response.status_code != 200:
        raise HTTPException(response.status_code, "Document preview access unavailable")
    return response.json()


@router.post("/document-desk/artifacts/{ident}/authorization")
def preview_authorization(ident: UUID, request: Request):
    row = authorize_artifact(request, ident)
    token = base64.urlsafe_b64encode(
        seal(
            json.dumps(
                {
                    "id": str(ident),
                    "expires": int(time.time()) + 60,
                    "org": request.headers.get("X-Organization-Id"),
                    "user": (identity.get() or {}).get("id"),
                }
            ).encode(),
            "document-preview",
        )
    ).decode()
    return {
        "url": f"/api/services/document/document-desk/artifacts/{ident}/content?token={token}",
        "expires_in_seconds": 60,
        "sha256": row["sha256"],
    }


@router.get("/document-desk/artifacts/{ident}/content")
def preview_content(ident: UUID, request: Request, token: str):
    try:
        basis = json.loads(unseal(base64.urlsafe_b64decode(token), "document-preview"))
    except Exception as exc:
        raise HTTPException(403, "Invalid preview authorization") from exc
    if (
        basis.get("id") != str(ident)
        or basis.get("expires", 0) < time.time()
        or basis.get("org") != request.headers.get("X-Organization-Id")
        or basis.get("user") != (identity.get() or {}).get("id")
    ):
        raise HTTPException(403, "Preview authorization expired or belongs to another profile")
    row = authorize_artifact(request, ident)
    content = plaintext(request.app.state.storage, artifact_key(row))
    if not secrets.compare_digest(hashlib.sha256(content).hexdigest(), row["sha256"]):
        raise HTTPException(503, "Preview integrity check failed")
    return Response(
        content,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
