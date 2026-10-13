"""Use the document key ring for authenticated, entity-bound private identity storage."""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.operations.access import fail


def keyring():
    try:
        raw = os.getenv("DOCUMENT_ENCRYPTION_KEY")
        ring = (
            {"active": "env-v1", "keys": {"env-v1": raw}}
            if raw
            else json.loads(
                Path(
                    os.getenv("DOCUMENT_ENCRYPTION_KEY_FILE", ".secrets/document-keyring.json")
                ).read_text(encoding="utf-8")
            )
        )
        keys = {
            name: base64.b64decode(value, validate=True) for name, value in ring["keys"].items()
        }
        if ring["active"] not in keys or any(len(key) != 32 for key in keys.values()):
            raise ValueError("Invalid key ring")
        return ring["active"], keys
    except (OSError, KeyError, ValueError, TypeError):
        fail(
            "PRIVATE_STORAGE_UNAVAILABLE",
            "Private identity encryption is unavailable; configure the document key ring.",
            status=503,
        )


def seal(value, organisation_id, entity_id):
    active, keys = keyring()
    nonce = os.urandom(12)
    aad = f"phase4-private|{organisation_id}|{entity_id}|{active}".encode()
    ciphertext = AESGCM(keys[active]).encrypt(
        nonce, json.dumps(value, sort_keys=True, separators=(",", ":")).encode(), aad
    )
    return {
        "schema": "PH4_PRIVATE_ENVELOPE_V1",
        "kid": active,
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def unseal(envelope, organisation_id, entity_id):
    try:
        _, keys = keyring()
        aad = f"phase4-private|{organisation_id}|{entity_id}|{envelope['kid']}".encode()
        content = AESGCM(keys[envelope["kid"]]).decrypt(
            base64.b64decode(envelope["nonce"], validate=True),
            base64.b64decode(envelope["ciphertext"], validate=True),
            aad,
        )
        return json.loads(content)
    except Exception:
        fail(
            "PRIVATE_STORAGE_UNAVAILABLE",
            "Private record integrity/key verification failed.",
            status=503,
        )


def identity_hash(pan):
    active, keys = keyring()
    return hmac.new(keys[active], f"pan-identity|{pan}".encode(), hashlib.sha256).hexdigest()
