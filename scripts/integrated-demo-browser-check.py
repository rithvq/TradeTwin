"""Real browser + encrypted document pipeline on disposable local stores.

Only the scanner's INSTREAM response is stubbed, as in the document-desk
acceptance. No login bypass, parser stub, seeded permissions on the real user,
production data, external routing call or production credentials are used.
"""

import base64
import hashlib
import importlib.util
import os
import secrets
import socket
import socketserver
import sqlite3
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
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:3149"
OUTPUT = ROOT / "artifacts/audit/integrated-demo"
spec = importlib.util.spec_from_file_location(
    "document_browser", ROOT / "scripts/document-browser-check.py"
)
documents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documents)
smoke = documents.smoke


def exercise(tokens, folder):
    base = f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1"
    headers = {"Authorization": "Bearer " + tokens[0]}
    with httpx.Client(timeout=45) as client, sync_playwright() as playwright:

        def read(path, org=None):
            response = client.get(
                base + path, headers={**headers, **({"X-Organization-Id": org} if org else {})}
            )
            response.raise_for_status()
            return response.json()

        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chromium"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(30000)
        expect.set_options(timeout=30000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.context.add_cookies(
            [
                {
                    "name": "tt_session",
                    "value": tokens[0],
                    "url": ORIGIN,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page.goto(ORIGIN + "/dashboard")
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/demo-sessions")
        ) as pending:
            page.get_by_role("button", name="TradeTwin Demo", exact=True).click()
        assert pending.value.status == 202, pending.value.text()
        ident = pending.value.json()["id"]
        page.wait_for_url("**/demo/" + ident)

        def ready():
            for _ in range(360):
                value = read("/demo-sessions/" + ident)
                if value["status"] == "FAILED":
                    raise AssertionError(value["receipts"])
                if value["status"] == "READY":
                    return value
                time.sleep(0.5)
            raise AssertionError("Demo worker did not complete")

        demo = ready()
        print("PASS: ordinary profile launched encrypted integrated simulation", flush=True)
        org, cn = demo["organization_id"], demo["consignment_id"]
        deny = client.get(
            base + "/demo-sessions/" + ident, headers={"Authorization": "Bearer " + tokens[1]}
        )
        assert deny.status_code == 404
        assert (
            client.get(
                base + f"/trades/{demo['trade_id']}/operations",
                headers={"Authorization": "Bearer " + tokens[1], "X-Organization-Id": org},
            ).status_code
            == 403
        )
        extracted = read(
            "/document-versions/" + demo["sample_document_version_id"] + "/extraction-runs", org
        )
        assert extracted["items"], extracted.keys()
        assert extracted["items"][0]["engine_kind"] != "SIMULATION_FIXTURE"
        canonical = extracted["items"][0]["proposed_document_json"]
        assert canonical["header"]["document_number"] == "INV-000001"
        assert canonical["lines"][0]["quantity"] == "100"
        assert canonical["totals"]["grand_total_minor"] == "1180000"
        assert list((folder / "objects").rglob("*.enc")), "No encrypted originals"
        assert all(
            not path.read_bytes().startswith(b"%PDF")
            for path in (folder / "objects").rglob("*.enc")
        )
        print(
            "PASS: PDF AUTO extraction, encrypted originals and second-profile isolation",
            flush=True,
        )
        expect(page.get_by_role("link", name="Open parsed sample PDF", exact=False)).to_be_visible()
        page.get_by_role("link", name="Open parsed sample PDF", exact=False).click()
        expect(
            page.get_by_role("heading", name="SIMULATION extraction sample", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="Return to demo", exact=True).click()
        expect(page.get_by_role("button", name="Run next demo step", exact=True)).to_be_enabled()
        expect(page.get_by_role("table", name="Freight route alternatives")).to_be_visible()
        for width in [1440, 390]:
            page.set_viewport_size({"width": width, "height": 1000})
            page.screenshot(path=str(OUTPUT / f"overview-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        for label in [
            "Commercial agreement",
            "Documents & extraction",
            "Freight & route optimizer",
            "Compliance & trace",
            "Shipment graph",
            "Corridor intelligence",
            "Receipts & inspection",
            "Payments",
            "Decision replay & evidence",
            "Rule registry",
        ]:
            link = page.get_by_role("navigation", name="Demo features").get_by_role(
                "link", name=label, exact=False
            )
            href = link.get_attribute("href")
            page.goto(ORIGIN + href)
            expect(page.get_by_role("heading", name="Trade workspace", exact=True)).to_be_visible()
            # Wait for ordinary module data; any inaccessible server resource is a failure.
            page.wait_for_function("""() => !Array.from(document.querySelectorAll('[role=status]'))
                .some(node => node.textContent.trim().startsWith('Loading'))""")
            historical_notice = (
                "Historical comparison. Changed or expired inputs require a new BASE run."
            )
            alerts = [
                a
                for a in page.get_by_role("alert").all_text_contents()
                if a.strip() and a.strip() != historical_notice
            ]
            assert not alerts, (label, alerts)
            print("PASS: feature " + label, flush=True)
            if label == "Decision replay & evidence":
                cn_view = read(f"/consignments/{cn}", org)
                section = page.get_by_role(
                    "region", name="Freight planning " + cn_view["reference"], exact=True
                )
                with page.expect_response(
                    lambda r: r.request.method == "POST"
                    and r.url.endswith("/evidence/replay-requests")
                ) as replay:
                    section.get_by_role(
                        "button", name="Recompute captured inputs", exact=True
                    ).click()
                assert replay.value.status == 202, replay.value.text()
                replay_id = replay.value.json()["id"]
                for _ in range(100):
                    result = read("/evidence/replay-results/" + replay_id, org)
                    if result["job_state"] == "COMPLETED":
                        break
                    time.sleep(0.3)
                assert result.get("input_integrity") == "PASS", result
                assert result.get("recomputation") == "MATCH", result
            page.get_by_role("link", name="Return to demo", exact=True).click()
            expect(page.get_by_role("navigation", name="Demo features")).to_be_visible()
        print("PASS: all ten feature links open the current ordinary product screens", flush=True)
        for index, step in enumerate(demo["steps"]):
            expect(
                page.get_by_role("button", name="Run next demo step", exact=True)
            ).to_be_enabled()
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.endswith("/steps")
            ) as pending:
                page.get_by_role("button", name="Run next demo step", exact=True).click()
            assert pending.value.status == 202, pending.value.text()
            state = ready()
            assert state["next_step_index"] == index + 1, state
            page.reload()
            if step["code"] in {"PICKUP_RELEASE", "PICKUP", "DEPARTURE_RELEASE", "DEPART"}:
                action = "PICKUP_CONFIRMED" if step["code"].startswith("PICKUP") else "DEPARTED"
                journey = read(f"/consignments/{cn}/dispatch-journey?action={action}", org)
                authorization = next(s for s in journey["stages"] if s["number"] == 5)
                expected = "ACTIVE" if step["code"].endswith("RELEASE") else "CONSUMED"
                assert authorization["status"] == expected, authorization
            print("PASS: " + step["code"], flush=True)
        expect(
            page.get_by_text(
                "Journey complete. Movement, receipt and declared payment are recorded.", exact=True
            )
        ).to_be_visible()
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/demo/seed")
        ) as classic:
            page.get_by_role("button", name="Original shipment scenario", exact=True).click()
        assert classic.value.status == 200, classic.value.text()
        page.wait_for_url("**/shipments/" + classic.value.json()["id"])
        page.get_by_role("link", name="Return to demo", exact=True).click()
        expect(page.get_by_role("button", name="Start fresh demo", exact=True)).to_be_enabled()
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/demo-sessions")
        ) as pending:
            page.get_by_role("button", name="Start fresh demo", exact=True).click()
        assert pending.value.status == 202
        assert pending.value.json()["id"] != ident
        assert read("/demo-sessions/" + ident)["next_step_index"] == 8
        page.get_by_role("button", name="Exit demo", exact=True).click()
        assert page.evaluate("sessionStorage.getItem('tt-demo-active')") is None
        assert page.evaluate("localStorage.getItem('tt-commercial-org')") is None
        assert not errors, errors
        browser.close()
        print("PASS: fresh session preserves history; exiting restores profile context", flush=True)


def main():
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 3149)) == 0:
            raise RuntimeError("Port 3149 occupied; refusing to replace an existing server")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-integrated-demo-"))
        )
        scanner = socketserver.ThreadingTCPServer(("127.0.0.1", 0), documents.ScannerFixture)
        stack.callback(scanner.server_close)
        stack.callback(scanner.shutdown)
        threading.Thread(target=scanner.serve_forever, daemon=True).start()
        extra = {
            "PROFILE_AUTH_ENABLED": "true",
            "IN_APP_DEMO_ENABLED": "true",
            "DOCUMENT_DEMO_ENABLED": "false",
            "APP_PUBLIC_URL": ORIGIN,
            "API_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['api']}",
            "DOCUMENT_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
            "DOCUMENT_WORKER_TOKEN": secrets.token_urlsafe(48),
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "EVIDENCE_CLAMAV_HOST": "127.0.0.1",
            "EVIDENCE_CLAMAV_PORT": str(scanner.server_address[1]),
            "DOCUMENT_OCR_ENGINE": "disabled",
            "ALLOW_EXTERNAL_ROUTING": "false",
        }
        smoke.start_local(stack, folder, extra)
        tokens = [secrets.token_urlsafe(48) for _ in range(2)]
        with closing(sqlite3.connect(folder / "api.db")) as db, db:
            for index, token in enumerate(tokens):
                subject = str(uuid4())
                db.execute(
                    "INSERT INTO auth_profiles VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        subject,
                        "https://test.invalid",
                        subject,
                        f"viewer{index}@example.invalid",
                        "Demo viewer",
                        datetime.now(UTC).isoformat(),
                    ),
                )
                db.execute(
                    "INSERT INTO auth_sessions VALUES (?, ?, ?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        subject,
                        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    ),
                )
        env = {
            **os.environ,
            **extra,
            "DATABASE_URL": f"sqlite+pysqlite:///{folder / 'shipment.db'}",
            "NEO4J_ENABLED": "false",
            "LOCAL_OBJECT_STORAGE_PATH": str(folder / "objects"),
            "DOCUMENT_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['document']}",
            "DOCUMENT_WORKER_HEARTBEAT_FILE": str(folder / "heartbeat"),
        }
        for name, port in smoke.SERVICES.items():
            env[f"{'API' if name == 'api' else name.upper()}_SERVICE_URL"] = (
                f"http://127.0.0.1:{port}"
            )
        worker_log = stack.enter_context((folder / "worker.log").open("w+"))
        worker = subprocess.Popen(
            [sys.executable, "-m", "app.document_desk.worker"],
            cwd=ROOT / "services/shipment-service",
            env=env,
            stdout=worker_log,
            stderr=worker_log,
        )
        stack.callback(stop_process, worker)
        web_log = stack.enter_context((folder / "web.log").open("w+"))
        web = subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--port", "3149"],
            cwd=ROOT / "apps/web",
            env=env,
            stdout=web_log,
            stderr=web_log,
        )
        stack.callback(stop_process, web)
        for _ in range(100):
            try:
                httpx.get(ORIGIN + "/login", timeout=1).raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.3)
        try:
            exercise(tokens, folder)
        except Exception:
            # These are disposable fixtures only. Never copy auth/worker tokens.
            with closing(sqlite3.connect(folder / "shipment.db")) as db:
                print(
                    "Demo job diagnostics:",
                    db.execute(
                        "SELECT stage,status,last_error_code FROM doc_processing_jobs "
                        "WHERE status IN ('FAILED','RUNNING')"
                    ).fetchall(),
                )
            raise


if __name__ == "__main__":
    main()
