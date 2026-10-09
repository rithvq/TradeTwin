"""Exercise two session identities across isolated services without OAuth credentials."""

import hashlib
import importlib.util
import secrets
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ORIGIN = "http://localhost:3000"
spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts/smoke-test.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
smoke.SERVICES = {name: port + 11000 for name, port in smoke.SERVICES.items()}


def exercise(folder):
    alice, bob = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    with closing(sqlite3.connect(folder / "api.db")) as db, db:
        for name, token in [("alice", alice), ("bob", bob)]:
            db.execute(
                "INSERT INTO auth_profiles(id, issuer, subject, email, name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    name,
                    "https://test.invalid",
                    name,
                    name + "@test.invalid",
                    name,
                    datetime.now(UTC).isoformat(),
                ),
            )
            db.execute(
                "INSERT INTO auth_sessions VALUES (?, ?, ?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    name,
                    (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                ),
            )
    with httpx.Client(timeout=60) as client:

        def call(service, method, path, token=alice, expected=200, **kwargs):
            response = client.request(
                method,
                f"http://127.0.0.1:{smoke.SERVICES[service]}{path}",
                headers={"Authorization": f"Bearer {token}"} if token else {},
                **kwargs,
            )
            if response.status_code != expected:
                for name in [service, "document"]:
                    print((folder / f"{name}.log").read_text()[-5000:])
            assert response.status_code == expected, (
                service,
                method,
                path,
                response.status_code,
                response.text[:300],
            )
            return response

        for name, path in [
            ("shipment", "/shipments"),
            ("document", "/documents/unknown"),
            ("compliance", "/audit-logs"),
            ("intelligence", "/shipments/x/risk-assessment"),
        ]:
            call(name, "GET", path, token=None, expected=401)
            call(name, "GET", path, token="forged-owner-alice", expected=401)
        a = call("shipment", "POST", "/demo/seed").json()
        b = call("shipment", "POST", "/demo/seed", token=bob).json()
        assert a["id"] != b["id"] and a["shipment_reference"] == b["shipment_reference"]
        aid, bid = a["id"], b["id"]
        call("compliance", "POST", f"/state-relations/{aid}/observe")
        call("compliance", "GET", f"/state-relations/{aid}", token=bob, expected=404)
        assert (
            call("compliance", "GET", f"/state-relations/{bid}", token=bob).json()["records"] == []
        )
        assert [s["id"] for s in call("shipment", "GET", "/shipments").json()] == [aid]
        assert [s["id"] for s in call("shipment", "GET", "/shipments", token=bob).json()] == [bid]
        for suffix in ["", "/graph", "/timeline"]:
            call("shipment", "GET", f"/shipments/{aid}{suffix}", token=bob, expected=404)
        call("shipment", "DELETE", f"/shipments/{aid}", token=bob, expected=404)
        upload_args = {
            "data": {"document_type": "safety_certificate", "jurisdiction": "UAE"},
            "files": {
                "file": (
                    "safety.txt",
                    b"Document Number: PRIVATE-ALICE\nProduct Name: Lithium batteries",
                    "text/plain",
                )
            },
        }
        call(
            "document",
            "POST",
            f"/shipments/{aid}/documents",
            token=bob,
            expected=404,
            **upload_args,
        )
        doc = call(
            "document", "POST", f"/shipments/{aid}/documents", expected=201, **upload_args
        ).json()
        did = doc["id"]
        assert (
            call("document", "POST", f"/documents/{did}/extract").json()["document_number"]
            == "PRIVATE-ALICE"
        )
        call("document", "GET", f"/documents/{did}", token=bob, expected=404)
        call("document", "POST", f"/documents/{did}/extract", token=bob, expected=404)
        call("document", "GET", f"/shipments/{aid}/documents", token=bob, expected=404)
        assessment = call("compliance", "POST", f"/compliance/evaluate/{aid}").json()
        assert call("compliance", "GET", f"/compliance/assessments/{aid}", token=bob).json() == []
        assert call("document", "GET", f"/assessments/{assessment['id']}/evidence").json()
        assert (
            call("document", "GET", f"/assessments/{assessment['id']}/evidence", token=bob).json()
            == []
        )
        call("compliance", "POST", f"/compliance/evaluate/{aid}", token=bob, expected=404)
        call("compliance", "GET", f"/reports/compliance/{aid}?format=pdf", token=bob, expected=404)
        assert call(
            "compliance", "GET", f"/reports/compliance/{aid}?format=pdf"
        ).content.startswith(b"%PDF")
        call("intelligence", "POST", f"/intelligence/risk-score/{aid}")
        call("intelligence", "GET", f"/shipments/{aid}/risk-assessment", token=bob, expected=404)
        assert call("compliance", "GET", "/audit-logs", token=bob).json() == []
        call("api", "POST", "/auth/logout", expected=403)
        response = client.post(
            f"http://127.0.0.1:{smoke.SERVICES['api']}/auth/logout",
            headers={"Authorization": f"Bearer {alice}", "Origin": PUBLIC_ORIGIN},
        )
        assert response.status_code == 200
        call("shipment", "GET", "/shipments", expected=401)
        call("shipment", "GET", "/shipments", token=bob)
    print(
        "PASS: separate profiles, demo seeds, private uploads/extraction/evidence/reports/risk, "
        "logout revocation"
    )


if __name__ == "__main__":
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-profiles-"))
        )
        smoke.start_local(
            stack,
            folder,
            {
                "PROFILE_AUTH_ENABLED": "true",
                "API_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['api']}",
                "APP_PUBLIC_URL": "http://localhost:3000",
            },
        )
        exercise(folder)
