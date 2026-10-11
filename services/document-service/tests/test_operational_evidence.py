"""Original bytes, encrypted storage, scanner fail-closed and scoped download tokens."""

import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["MINIO_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app import operational_evidence as evidence  # noqa: E402
from app.storage import ObjectStorage  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        evidence,
        "engine",
        create_engine(
            f"sqlite:///{tmp_path / 'locks.db'}", connect_args={"check_same_thread": False}
        ),
    )
    monkeypatch.setenv("LOCAL_OBJECT_STORAGE_PATH", str(tmp_path / "objects"))
    from app.config import settings

    monkeypatch.setattr(settings, "local_object_storage_path", tmp_path / "objects")
    storage = ObjectStorage()
    row = {
        "id": str(uuid4()),
        "trade_id": str(uuid4()),
        "size_bytes": 12,
        "content_type": "application/pdf",
        "security_state": "UPLOADING",
        "execution_mode": "SIMULATION",
    }
    key = f"operations/{row['trade_id']}/{row['id']}.enc"

    def authorize(request, ident, upload=False):
        if ident != row["id"] or request.headers.get("X-Organization-Id") != "authorized":
            raise HTTPException(403, "Evidence access unavailable")
        return row, key

    monkeypatch.setattr(evidence, "authorize", authorize)
    app = FastAPI()
    app.state.storage = storage
    app.include_router(evidence.router)
    with TestClient(app) as client:
        yield client, row, storage, key
    evidence.engine.dispose()


def test_encrypted_original_bytes_and_server_hash_fail_closed(store, monkeypatch):
    client, row, storage, key = store
    body = b"%PDF-demo123"
    row["size_bytes"] = len(body)
    path = f"/operational-evidence/{row['id']}"
    headers = {"X-Organization-Id": "authorized", "Idempotency-Key": str(uuid4())}
    response = client.put(
        path + "/content", headers=headers, files={"file": ("demo.pdf", body, "application/pdf")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["sha256"] == hashlib.sha256(body).hexdigest()
    assert body not in storage.stored_bytes(key)
    assert evidence.plaintext(storage, key) == body
    assert (
        client.put(
            path + "/content",
            headers=headers,
            files={"file": ("demo.pdf", body, "application/pdf")},
        ).status_code
        == 200
    )
    assert (
        client.put(
            path + "/content",
            headers=headers,
            files={"file": ("demo.pdf", b"%PDF-other12", "application/pdf")},
        ).status_code
        == 409
    )
    monkeypatch.delenv("EVIDENCE_CLAMAV_HOST", raising=False)
    scan = client.get(path + "/inspection", headers=headers)
    assert scan.json()["security_state"] == "QUARANTINED"
    row["security_state"] = "QUARANTINED"
    assert client.post(path + "/download-authorization", headers=headers).status_code == 403
    row.update(security_state="CLEAN", sha256=hashlib.sha256(body).hexdigest())
    result = client.post(path + "/download-authorization", headers=headers)
    url = result.json()["url"].removeprefix("/api/services/document")
    assert client.get(url, headers=headers).content == body
    assert client.get(url, headers={"X-Organization-Id": "unrelated"}).status_code == 403
    assert client.get(path + "/download?token=bad", headers=headers).status_code == 403


def test_conflicting_concurrent_uploads_keep_one_original(store):
    client, row, storage, key = store
    bodies = (b"%PDF-first12", b"%PDF-other12")
    row["size_bytes"] = len(bodies[0])

    def upload(index):
        return client.put(
            f"/operational-evidence/{row['id']}/content",
            headers={"X-Organization-Id": "authorized", "Idempotency-Key": str(uuid4())},
            files={"file": ("demo.pdf", bodies[index], "application/pdf")},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(upload, (0, 1)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert evidence.plaintext(storage, key) in bodies


def test_scanner_failure_cannot_grant_clean(monkeypatch):
    monkeypatch.setenv("EVIDENCE_CLAMAV_HOST", "scanner.invalid")
    monkeypatch.setattr(
        evidence.socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(OSError("Unavailable")),
    )
    assert evidence.scan(b"%PDF-contents")[0] == "QUARANTINED"
