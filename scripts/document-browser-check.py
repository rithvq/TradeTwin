"""Disposable authenticated Phase 3 acceptance; scanner transport is stubbed only here."""

import base64
import hashlib
import importlib.util
import json
import os
import secrets
import socket
import socketserver
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack, closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from local_processes import stop_process
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/audit/document-desk"
ORIGIN = "http://localhost:3133"
spec = importlib.util.spec_from_file_location(
    "commercial", ROOT / "scripts/commercial-browser-check.py"
)
commercial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commercial)
smoke = commercial.smoke


class ScannerFixture(socketserver.BaseRequestHandler):
    """Exercises INSTREAM upload wiring, not malware-detection quality."""

    def handle(self):
        def receive(size):
            result = b""
            while len(result) < size:
                result += self.request.recv(size - len(result))
            return result

        assert receive(10) == b"zINSTREAM\0"
        while size := struct.unpack("!I", receive(4))[0]:
            receive(size)
        self.request.sendall(b"stream: OK\0")


def exercise(fx, tokens):
    headers = {
        "Authorization": f"Bearer {tokens['seller-operations']}",
        "X-Organization-Id": fx["organizations"]["seller"],
    }
    base = f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1"
    with httpx.Client(timeout=45) as client, sync_playwright() as playwright:

        def request(method, path, body=None, etag=None):
            h = {**headers, "Idempotency-Key": str(uuid4())}
            if etag:
                h["If-Match"] = etag
            response = client.request(method, base + path, headers=h, json=body)
            response.raise_for_status()
            return response.json()

        def read_doc(name):
            return request("GET", f"/documents/{fx['documents'][name]}")

        def wait(job):
            for _ in range(120):
                value = request("GET", f"/document-processing-jobs/{job}")
                if value["status"] in {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}:
                    assert value["status"] in {"SUCCEEDED", "PARTIAL"}, value
                    return value
                time.sleep(0.5)
            raise AssertionError("Document job timed out")

        before = request("GET", f"/trades/{fx['trade_id']}/operations")
        trade = request("GET", f"/trades/{fx['trade_id']}")
        invoice = read_doc("invoice.pdf")
        vid = invoice["current_version_id"]
        wait(
            request(
                "POST",
                f"/document-versions/{vid}/processing-jobs",
                {"stage": "EXTRACT", "strategy": "NATIVE_TEXT"},
            )["job_id"]
        )
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.context.add_cookies(
            [
                {
                    "name": "tt_session",
                    "value": tokens["seller-operations"],
                    "url": ORIGIN,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )

        def save_review(version_id, correction=False):
            page.goto(f"{ORIGIN}/documents/versions/{version_id}/review")
            expect(page.get_by_role("heading", name="Captured values", exact=True)).to_be_visible()
            expect(page.get_by_label("Value header.document_number", exact=True)).to_have_value(
                "INV-000001"
            )
            expect(page.locator("img").first).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name="Save review draft", exact=True)).to_be_enabled()
            page.get_by_role("button", name="Confirm proposed values", exact=True).click()
            if correction:
                page.get_by_label("Value parties.supplier.gstin", exact=True).fill(
                    "33ABCDE1234F1Z5"
                )
                page.get_by_label("Reason parties.supplier.gstin", exact=True).fill(
                    "Corrected I to 1 against the visible source; simulation fixture."
                )
            decisions = page.locator('select[aria-label^="Decision "]')
            for decision in decisions.all():
                expect(decision).not_to_have_value("")
            try:
                with page.expect_response(
                    lambda r: "/fact-revisions" in r.url and r.request.method == "POST"
                ) as pending:
                    page.get_by_role("button", name="Save review draft", exact=True).click()
            except PlaywrightTimeoutError as problem:
                OUTPUT.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(OUTPUT / "review-save-failure.png"), full_page=True)
                alerts = page.get_by_role("alert").all_text_contents()
                raise AssertionError(
                    f"Review save sent no response. UI alerts: {alerts}; browser errors: {errors}"
                ) from problem
            assert pending.value.status == 201, pending.value.text()
            with page.expect_response(
                lambda r: "/submissions" in r.url and r.request.method == "POST"
            ) as submitted:
                page.get_by_role("button", name="Submit reviewed snapshot", exact=True).click()
            assert submitted.value.status == 200, submitted.value.text()
            expect(page.get_by_text("Reviewed", exact=True).first).to_be_visible()
            return pending.value.json()

        reviewed = save_review(vid)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUTPUT / "native-review-desktop.png"), full_page=True)
        invoice = read_doc("invoice.pdf")
        operations = request("GET", f"/trades/{fx['trade_id']}/operations")
        line = reviewed["canonical_document_json"]["lines"][0]
        portions = [
            {
                "document_line_ref": line["document_line_ref"],
                "trade_line_ref": cn["items"][0]["line_ref"],
                "target_kind": "CONSIGNMENT_ITEM",
                "consignment_item_id": cn["items"][0]["id"],
                "mapped_quantity": str(int(float(cn["items"][0]["allocated_quantity"]))),
                "uqc": "NOS",
            }
            for cn in operations["consignments"]
        ]
        request(
            "POST",
            f"/documents/{invoice['id']}/mapping-revisions",
            {
                "fact_revision_id": reviewed["id"],
                "accepted_trade_revision_id": trade["accepted_revision"]["id"],
                "base_mapping_revision_id": None,
                "mappings": portions,
            },
            invoice["etag"],
        )
        page.goto(f"{ORIGIN}/documents/{invoice['id']}/mapping")
        expect(page.get_by_text("Document total, recorded once:", exact=False)).to_contain_text(
            "11,800"
        )
        page.screenshot(path=str(OUTPUT / "mapping-desktop.png"), full_page=True)
        scanned = read_doc("scanned-invoice.png")
        wait(
            request(
                "POST",
                f"/document-versions/{scanned['current_version_id']}/processing-jobs",
                {"stage": "EXTRACT", "strategy": "SIMULATION_FIXTURE"},
            )["job_id"]
        )
        save_review(scanned["current_version_id"], True)
        evidence = request(
            "GET", f"/document-versions/{scanned['current_version_id']}/evidence-manifest"
        )
        assert any(
            o["normalised_value_json"] == "33ABCDEI234F1Z5" for o in evidence["observations"]
        )
        assert any(d["decision"] == "CORRECTED" for d in evidence["field_decisions"])
        scanned = read_doc("scanned-invoice.png")
        request(
            "POST",
            f"/documents/{scanned['id']}/relationships",
            {
                "to_document_id": invoice["id"],
                "relationship_type": "DUPLICATE_PRESENTATION_OF",
                "reason": "Reviewed scan is an alternate presentation "
                "of the canonical native invoice",
            },
            scanned["etag"],
        )
        signed = read_doc("signed-payload.json")
        sid = signed["current_version_id"]
        wait(
            request(
                "POST",
                f"/document-versions/{sid}/processing-jobs",
                {"stage": "EXTRACT", "strategy": "STRUCTURED_JSON"},
            )["job_id"]
        )
        signed = read_doc("signed-payload.json")
        signed_check = request(
            "POST",
            f"/document-versions/{sid}/verification-checks",
            {
                "check_type": "IRP_JSON_SIGNATURE",
                "fact_revision_id": signed["latest_draft_fact_revision_id"],
            },
        )
        wait(signed_check["job_id"])
        assert (
            request("GET", f"/document-verification-checks/{signed_check['check_id']}")["results"][
                0
            ]["result_json"]["signature_integrity"]
            == "VALID"
        )
        mismatched = read_doc("mismatched-invoice.pdf")
        mid = mismatched["current_version_id"]
        wait(
            request("POST", f"/document-versions/{mid}/processing-jobs", {"stage": "EXTRACT"})[
                "job_id"
            ]
        )
        mismatched = read_doc("mismatched-invoice.pdf")
        verify = request(
            "POST",
            f"/document-versions/{mid}/verification-checks",
            {
                "check_type": "IRP_QR_SIGNATURE",
                "fact_revision_id": mismatched["latest_draft_fact_revision_id"],
            },
        )
        wait(verify["job_id"])
        result = request("GET", f"/document-verification-checks/{verify['check_id']}")["results"][
            0
        ]["result_json"]
        assert (
            result["signature_integrity"] == "VALID" and result["lookup_outcome"] == "NOT_CHECKED"
        ), result
        assessment = request(
            "POST",
            f"/document-versions/{mid}/assessment-runs",
            {"fact_revision_id": mismatched["latest_draft_fact_revision_id"], "scope": "TRADE"},
        )
        wait(assessment["job_id"])
        summary = request("GET", f"/trades/{fx['trade_id']}/document-assessment-summary")
        assert any(
            s["check_code"] == "SIGNED_PAYLOAD_PRINTED_FIELD_MATCH" and s["outcome"] == "FAIL"
            for s in summary["signals"]
        )
        lookup = request(
            "POST",
            f"/document-versions/{vid}/verification-checks",
            {
                "check_type": "GSTIN_AUTHORITY_LOOKUP",
                "fact_revision_id": reviewed["id"],
                "target_field_path": "parties.supplier.gstin",
            },
        )
        wait(lookup["job_id"])
        assert (
            request("GET", f"/document-verification-checks/{lookup['check_id']}")["results"][0][
                "result_json"
            ]["lookup_outcome"]
            == "NOT_CONFIGURED"
        )
        for viewport in ({"width": 1440, "height": 1000}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            for tab in ("review", "findings", "verification", "evidence"):
                page.goto(f"{ORIGIN}/documents/versions/{vid}/{tab}")
                expect(page.get_by_role("heading", name="invoice.pdf", exact=True)).to_be_visible()
                page.wait_for_timeout(300)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), tab
            page.screenshot(path=str(OUTPUT / f"evidence-{viewport['width']}.png"), full_page=True)
        after = request("GET", f"/trades/{fx['trade_id']}/operations")
        for field in ("availability", "settlement", "schedules"):
            assert before.get(field) == after.get(field), field
        assert [cn["movement_status"] for cn in before["consignments"]] == [
            cn["movement_status"] for cn in after["consignments"]
        ]
        context = request("GET", f"/consignments/{fx['consignments'][0]}/document-context")
        assert context["linked_document_refs"] and context["document_context_hash"]
        invoice = read_doc("invoice.pdf")
        cn = request("GET", f"/consignments/{fx['consignments'][0]}")
        assessment_body = {
            "fact_revision_id": reviewed["id"],
            "mapping_revision_id": invoice["current_mapping_revision_id"],
            "scope": "CONSIGNMENT",
            "consignment_ids": [cn["id"]],
        }
        wait(
            request("POST", f"/document-versions/{vid}/assessment-runs", assessment_body)["job_id"]
        )
        previous = read_doc("invoice.pdf")["assessments"][0]["id"]
        request(
            "PATCH", f"/consignments/{cn['id']}", {"declared_gross_weight_kg": "500"}, cn["etag"]
        )
        assert request("GET", f"/document-assessment-runs/{previous}")["freshness"] == "STALE"
        wait(
            request("POST", f"/document-versions/{vid}/assessment-runs", assessment_body)["job_id"]
        )
        history = read_doc("invoice.pdf")["assessments"]
        assert history[0]["freshness"] == "CURRENT" and len(history) >= 2
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
            page.goto(f"{ORIGIN}/shipments/trades/{fx['trade_id']}/operations")
            commercial.key_button(page, "Graph")
            graph = (
                page.locator("section")
                .filter(
                    has=page.get_by_role("heading", name="Document provenance graph", exact=True)
                )
                .last
            )
            expect(graph.locator(".react-flow__node").first).to_be_visible(timeout=20000)
            assert graph.locator(".react-flow__edge").count() > 0
            page.screenshot(path=str(OUTPUT / f"provenance-graph-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()
    print(
        "PASS: real encrypted files/native extraction/previews, browser review and correction, "
        "40/60 mapping, exact QR signature + printed mismatch, no-provider result, "
        "manifests and mobile; "
        "accepted/operational facts unchanged. ClamAV transport stubbed in this isolated test only."
    )


def main(seed_module="app.document_desk.cli", exercise_fn=exercise):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 3133)) == 0:
            raise SystemExit("Port 3133 occupied; refusing to replace an existing server")
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-document-test-"))
        )
        scanner = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ScannerFixture)
        stack.callback(scanner.server_close)
        stack.callback(scanner.shutdown)
        threading.Thread(target=scanner.serve_forever, daemon=True).start()
        token = secrets.token_urlsafe(48)
        extra = {
            "DOCUMENT_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
            "PROFILE_AUTH_ENABLED": "true",
            "API_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['api']}",
            "APP_PUBLIC_URL": ORIGIN,
            "DOCUMENT_DEMO_ENABLED": "true",
            "DOCUMENT_WORKER_TOKEN": token,
            "DOCUMENT_FIXTURE_DIRECTORY": str(ROOT / "data/fixtures/document-desk"),
            "DOCUMENT_SIMULATION_FIXTURES_FILE": str(
                ROOT / "data/fixtures/document-desk/simulation-extraction.json"
            ),
            "EVIDENCE_CLAMAV_HOST": "127.0.0.1",
            "EVIDENCE_CLAMAV_PORT": str(scanner.server_address[1]),
        }
        smoke.start_local(stack, folder, extra)
        env = {
            **os.environ,
            **extra,
            "DATABASE_URL": f"sqlite+pysqlite:///{folder / 'shipment.db'}",
            "NEO4J_ENABLED": "false",
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "DOCUMENT_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['document']}",
        }
        seeded = subprocess.run(
            [sys.executable, "-m", seed_module],
            cwd=ROOT / "services/shipment-service",
            env=env,
            capture_output=True,
            text=True,
        )
        if seeded.returncode:
            raise RuntimeError(seeded.stderr)
        fx = json.loads(seeded.stdout)
        tokens = {name: secrets.token_urlsafe(48) for name in fx["subjects"]}
        with closing(sqlite3.connect(folder / "api.db")) as db, db:
            for name, subject in fx["subjects"].items():
                db.execute(
                    "INSERT INTO auth_profiles VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        subject,
                        "https://test.invalid",
                        subject,
                        f"{name}@example.invalid",
                        name,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                db.execute(
                    "INSERT INTO auth_sessions VALUES (?, ?, ?)",
                    (
                        hashlib.sha256(tokens[name].encode()).hexdigest(),
                        subject,
                        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    ),
                )
        log = stack.enter_context((folder / "worker.log").open("w+"))
        worker = subprocess.Popen(
            [sys.executable, "-m", "app.document_desk.worker"],
            cwd=ROOT / "services/shipment-service",
            env={**env, "DOCUMENT_WORKER_HEARTBEAT_FILE": str(folder / "heartbeat")},
            stdout=log,
            stderr=log,
        )
        stack.callback(stop_process, worker)
        for name, port in smoke.SERVICES.items():
            env[f"{'API' if name == 'api' else name.upper()}_SERVICE_URL"] = (
                f"http://127.0.0.1:{port}"
            )
        web_log = stack.enter_context((folder / "web.log").open("w+"))
        web = subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--port", "3133"],
            cwd=ROOT / "apps/web",
            env=env,
            stdout=web_log,
            stderr=web_log,
        )
        stack.callback(stop_process, web)
        for _ in range(100):
            try:
                if httpx.get(ORIGIN + "/login", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        try:
            exercise_fn(fx, tokens)
        except Exception:
            log.seek(0)
            print(log.read()[-8000:])
            raise


if __name__ == "__main__":
    main()
