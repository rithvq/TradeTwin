"""Authenticated application-layer encryption; keys never enter the database or bucket."""

import base64
import json
import os
from datetime import date
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON, TypeDecorator
from tradetwin_security import owner_id

from app.config import settings

MAGIC = b"TTENC1\n"
JSON_MARKER = "__tt_encrypted__"


class EncryptionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def keyring():
    try:
        if settings.document_encryption_key:
            data = {"active": "env-v1", "keys": {"env-v1": settings.document_encryption_key}}
        else:
            data = json.loads(settings.document_encryption_key_file.read_text(encoding="utf-8"))
        keys = {
            name: base64.b64decode(value, validate=True) for name, value in data["keys"].items()
        }
        if not keys or any(len(key) != 32 for key in keys.values()) or data["active"] not in keys:
            raise ValueError("Invalid key ring")
        return data["active"], keys
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EncryptionError("Document encryption key is missing or invalid") from exc


def seal(content: bytes, context: str) -> bytes:
    active, keys = keyring()
    nonce = os.urandom(12)
    ciphertext = AESGCM(keys[active]).encrypt(nonce, content, f"{context}|{active}".encode())
    return (
        MAGIC
        + json.dumps(
            {
                "kid": active,
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
            separators=(",", ":"),
        ).encode()
    )


def unseal(content: bytes, context: str) -> bytes:
    try:
        if not content.startswith(MAGIC):
            raise ValueError("Unencrypted content")
        envelope = json.loads(content[len(MAGIC) :])
        _, keys = keyring()
        return AESGCM(keys[envelope["kid"]]).decrypt(
            base64.b64decode(envelope["nonce"], validate=True),
            base64.b64decode(envelope["ciphertext"], validate=True),
            f"{context}|{envelope['kid']}".encode(),
        )
    except Exception as exc:
        raise EncryptionError("Encrypted document integrity or key verification failed") from exc


def field_context(field: str, owner: str | None = None):
    return f"document-db|{owner if owner is not None else owner_id()}|{field}"


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, field: str, as_date: bool = False):
        super().__init__()
        self.field = field
        self.as_date = as_date

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = value.isoformat() if self.as_date else value
        return seal(value.encode(), field_context(self.field)).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        result = unseal(value.encode(), field_context(self.field)).decode()
        return date.fromisoformat(result) if self.as_date else result


class EncryptedJSON(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, field: str):
        super().__init__()
        self.field = field

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSONB() if dialect.name == "postgresql" else JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return {JSON_MARKER: seal(json.dumps(value).encode(), field_context(self.field)).decode()}

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, dict) or JSON_MARKER not in value:
            raise EncryptionError("Unencrypted document metadata; migration required")
        return json.loads(unseal(value[JSON_MARKER].encode(), field_context(self.field)))
