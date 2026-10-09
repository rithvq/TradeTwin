# ruff: noqa: E402, I001
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from tradetwin_security import identity

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["MINIO_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app import encryption as crypto
from app.config import settings
from app.database import engine
from app.encryption_migration import migrate_encryption
from app.main import app
from app.storage import ObjectStorage


def test_authenticated_encryption_random_nonce_and_context():
    a = crypto.seal(b"confidential invoice", "document-a")
    b = crypto.seal(b"confidential invoice", "document-a")
    assert a != b
    assert b"confidential invoice" not in a
    assert crypto.unseal(a, "document-a") == b"confidential invoice"
    for data, context in [
        (a, "document-b"),
        (a[:-5] + b"wrong", "document-a"),
        (b"plaintext", "document-a"),
    ]:
        with pytest.raises(crypto.EncryptionError):
            crypto.unseal(data, context)


def test_upload_extract_database_and_object_are_encrypted(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "local_object_storage_path", tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/shipments/private-test/documents",
            data={"document_type": "commercial_invoice"},
            files={
                "file": (
                    "secret-invoice.txt",
                    b"Document Number: SECRET-918\nQuantity: 45",
                    "text/plain",
                )
            },
        )
        assert response.status_code == 201
        doc = response.json()
        response = client.post(f"/documents/{doc['id']}/extract")
        assert response.status_code == 200
        assert response.json()["document_number"] == "SECRET-918"
        with engine.connect() as connection:
            row = (
                connection.execute(text("SELECT * FROM documents WHERE id=:id"), {"id": doc["id"]})
                .mappings()
                .one()
            )
        assert "SECRET-918" not in str(dict(row))
        assert "secret-invoice.txt" not in row["filename"]
        assert "secret-invoice" not in row["object_key"]
        content = (tmp_path / row["object_key"]).read_bytes()
        assert content.startswith(crypto.MAGIC)
        assert b"SECRET-918" not in content
        response = client.post(
            "/shipments/private-test/documents",
            content=b"",
            headers={"Content-Length": str(settings.max_upload_bytes + 100000)},
        )
        assert response.status_code == 413


def test_profile_bound_metadata_and_object_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "local_object_storage_path", tmp_path)
    column = crypto.EncryptedText("documents.filename")
    token = identity.set({"id": "alice"})
    try:
        encrypted = column.process_bind_param("private.txt", None)
        assert column.process_result_value(encrypted, None) == "private.txt"
        identity.set({"id": "bob"})
        with pytest.raises(crypto.EncryptionError):
            column.process_result_value(encrypted, None)
        with pytest.raises(crypto.EncryptionError):
            ObjectStorage().get_bytes("profiles/alice/file.enc")
        with pytest.raises(crypto.EncryptionError):
            ObjectStorage().stored_bytes("../../outside")
    finally:
        identity.reset(token)


def test_legacy_migration_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "local_object_storage_path", tmp_path)
    db = create_engine("sqlite+pysqlite:///:memory:")
    storage = ObjectStorage()
    storage.put_bytes("legacy.txt", b"Original confidential contents")
    with db.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE documents (id TEXT, owner_id TEXT, shipment_id TEXT, "
                "object_key TEXT, filename TEXT, extracted_fields JSON, "
                "extracted_text_preview TEXT, document_number TEXT, document_date DATE)"
            )
        )
        conn.execute(
            text("CREATE TABLE evidence_records (id TEXT, owner_id TEXT, explanation TEXT)")
        )
        conn.execute(
            text(
                "INSERT INTO documents VALUES ('doc', 'alice', 'shipment', 'legacy.txt', "
                "'private.txt', :fields, 'PRIVATE PREVIEW', 'PRIVATE NUMBER', '2026-09-14')"
            ),
            {"fields": json.dumps({"quantity": 123})},
        )
    migrate_encryption(db, storage)
    migrate_encryption(db, storage)
    with db.connect() as conn:
        row = conn.execute(text("SELECT * FROM documents")).mappings().one()
    assert row["document_date"].startswith(crypto.MAGIC.decode())
    assert "PRIVATE" not in str(dict(row))
    assert storage.stored_bytes("legacy.txt").startswith(crypto.MAGIC)
    assert (
        crypto.unseal(
            storage.stored_bytes(row["object_key"]), f"document-object|{row['object_key']}"
        )
        == b"Original confidential contents"
    )
    db.dispose()


def test_missing_key_and_retained_key_rotation(monkeypatch, tmp_path):
    original = crypto.keyring()
    crypto.keyring.cache_clear()
    monkeypatch.setattr(settings, "document_encryption_key", None)
    monkeypatch.setattr(settings, "document_encryption_key_file", tmp_path / "missing")
    with pytest.raises(crypto.EncryptionError):
        crypto.seal(b"data", "context")
    old, keys = original
    monkeypatch.setattr(crypto, "keyring", lambda: (old, keys))
    previous = crypto.seal(b"data", "context")
    rotated = {**keys, "new": os.urandom(32)}
    monkeypatch.setattr(crypto, "keyring", lambda: ("new", rotated))
    assert crypto.unseal(previous, "context") == b"data"
    assert b'"kid":"new"' in crypto.seal(b"data", "context")


def test_minio_receives_only_ciphertext(monkeypatch):
    import asyncio
    from io import BytesIO

    stored = {}

    class FakeMinio:
        def put_object(self, bucket, key, stream, **kwargs):
            stored[key] = stream.read()

    storage = ObjectStorage()
    storage.client = FakeMinio()
    key, size = asyncio.run(
        storage.put_upload(
            "shipment",
            "doc",
            UploadFile(filename="invoice.txt", file=BytesIO(b"confidential amount 123456")),
        )
    )
    assert size == 26
    assert stored[key].startswith(crypto.MAGIC)
    assert b"confidential amount" not in stored[key]
