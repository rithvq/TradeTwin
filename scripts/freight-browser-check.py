"""Authenticated Phase 5 acceptance on disposable profiles, services and simulation data."""

import base64
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from local_processes import stop_process
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:3145"
OUTPUT = ROOT / "artifacts/audit/freight"
spec = importlib.util.spec_from_file_location(
    "operations_browser", ROOT / "scripts/operations-browser-check.py"
)
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)
smoke = operations.smoke


def exercise(fx, tokens, fixture_file, env):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright, httpx.Client(timeout=30) as client:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chromium"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(30000)
        expect.set_options(timeout=30000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        path = f"/shipments/trades/{fx['trade_id']}/operations"

        def signin(role, path=path):
            page.context.clear_cookies()
            page.context.add_cookies(
                [
                    {
                        "name": "tt_session",
                        "value": tokens[role],
                        "url": ORIGIN,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
            page.goto(ORIGIN + path)
            expect(page.get_by_role("heading", name="Trade workspace", exact=True)).to_be_visible()

        def read(path, role="seller-approver", side="seller"):
            response = client.get(
                f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1{path}",
                headers={
                    "Authorization": "Bearer " + tokens[role],
                    "X-Organization-Id": fx["organizations"][side],
                },
            )
            response.raise_for_status()
            return response.json()

        def action(locator, suffix):
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.endswith(suffix)
            ) as pending:
                locator.click()
            assert pending.value.status in {200, 201, 202}, pending.value.text()
            return pending.value.json()

        def module(name):
            page.get_by_role("navigation", name="Trade modules", exact=True).get_by_role(
                "button", name=name, exact=True
            ).click()

        signin("seller-operations")
        print("Authenticated planner", flush=True)
        module("Optimizer")
        route_studio = page.get_by_role("region", name="India freight route intelligence")
        expect(route_studio).to_be_visible()
        route_studio.get_by_label("Route source", exact=True).select_option("RETAINED")
        dataset = route_studio.get_by_label("Retained route dataset")
        dataset.select_option(index=1)
        route_study = action(
            route_studio.get_by_role("button", name="Compare freight routes", exact=True),
            "/freight-route-studies",
        )
        queued = read(f"/freight-route-studies/{route_study['id']}", "seller-operations", "seller")
        # The browser harness normally runs single-job workers explicitly for deterministic QA.
        worker_code = (
            "from app.database import SessionLocal; "
            "from app.freight_routes.models import RouteStudy; "
            "from app.document_desk.worker import run_one; "
            "db=SessionLocal(); "
            f"row=db.get(RouteStudy, {route_study['id']!r}); job=row.job_id; db.close(); "
            "assert run_one(SessionLocal, job)"
        )
        assert queued["source_mode"] == "RETAINED"
        subprocess.run(
            [sys.executable, "-c", worker_code],
            cwd=ROOT / "services/shipment-service",
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        result = route_studio.get_by_role("region", name="Freight route comparison result")
        expect(result.get_by_role("table", name="Freight route alternatives")).to_be_visible()
        expect(result.get_by_role("img", name="Compared freight road routes")).to_be_visible()
        expect(result.get_by_text("Retained topology schematic", exact=False)).to_be_visible()
        assert not result.get_by_role("button", name="Record pickup", exact=True).count()
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            result.scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT / f"state-routes-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1440, "height": 1000})
        print("PASS: state-wise route graph, ranked alternatives and mobile layout", flush=True)
        table = page.get_by_role("table", name="Freight candidate comparison")
        expect(table).to_be_visible()
        expect(table.get_by_text("Carrier quote", exact=True)).to_have_count(0)
        row = table.get_by_role("row").filter(has_text="Offer A")
        proposal = action(
            row.get_by_role("button", name="Propose", exact=True), "/tradetwin-selections"
        )
        print("Proposed BASE offer A without spending access", flush=True)
        signin("seller-approver")
        module("Optimizer")
        expect(page.get_by_text("INR 3,150.00", exact=False)).to_be_visible()
        table = page.get_by_role("table", name="Freight candidate comparison")
        expect(table.get_by_text("Rank 1 / Pareto", exact=True)).to_be_visible()
        expect(table.get_by_text("Needs Input", exact=True)).to_be_visible()
        expect(table.get_by_text("Incomplete", exact=True)).to_be_visible()
        for viewport in [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}]:
            page.set_viewport_size(viewport)
            expect(table).to_be_visible()
            page.screenshot(
                path=str(OUTPUT / f"comparison-{viewport['width']}.png"), full_page=True
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                page.evaluate(
                    """Array.from(document.querySelectorAll('main *')).filter(e => {
                    const r = e.getBoundingClientRect(); return r.right > innerWidth + 1;
                }).slice(0, 10).map(e => ({tag: e.tagName, classes: e.className,
                    text: e.textContent.slice(0, 90)}))"""
                )
            )
        page.set_viewport_size({"width": 1440, "height": 1000})
        section = (
            page.locator("section")
            .filter(has=page.get_by_role("heading", name="Transport-plan commitment", exact=True))
            .last
        )
        section.get_by_label("Reason", exact=False).fill(
            "Procurement approves exact synthetic fixed offer"
        )
        for checkbox in section.get_by_role("checkbox").all():
            checkbox.check()
        approved = action(
            section.get_by_role("button", name="Approve exact freight offer", exact=True),
            "/payer-decisions",
        )
        print("Desktop/mobile comparison and exact payer approval passed", flush=True)
        signin("carrier-dispatcher", "/optimizer/freight")
        page.get_by_label("Selection request", exact=True).select_option(proposal["id"])
        consent = (
            page.locator("section")
            .filter(has=page.get_by_role("heading", name="Carrier acceptance", exact=True))
            .last
        )
        consent.get_by_label("Reason", exact=False).fill(
            "Explicit carrier acceptance of exact route, offer and resources"
        )
        accepted = action(
            consent.get_by_role("button", name="Decide exact freight commitment", exact=True),
            "/carrier-decisions",
        )
        print("Explicit carrier acceptance passed", flush=True)
        assert accepted["accepted_assignment_id"] == approved["proposed_assignment_id"]
        assert accepted["dispatch_authorisation"] is None
        readiness = read(
            f"/consignments/{fx['consignment_id']}/dispatch-readiness?action=PICKUP_CONFIRMED"
        )
        assert readiness["state"] != "READY"
        refreshed = subprocess.run(
            [sys.executable, "-m", "app.freight.cli", "--refresh-fixture", str(fixture_file)],
            cwd=ROOT / "services/shipment-service",
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(refreshed.stdout)["authorisation_id"]
        assert (
            read(
                f"/consignments/{fx['consignment_id']}/dispatch-readiness?action=PICKUP_CONFIRMED"
            )["state"]
            == "READY"
        )
        signin("seller-approver")
        module("Evidence")
        expect(page.get_by_role("heading", name="Decision replay", exact=True)).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("button", name="Evidence manifest", exact=True).click()
        assert download.value.suggested_filename.endswith(".json")
        module("Graph")
        expect(
            page.get_by_role("region", name="Freight decision relationships", exact=True)
        ).to_be_visible()
        page.screenshot(path=str(OUTPUT / "decision-graph.png"), full_page=True)
        # Private comparison is not accessible to assigned drivers or unrelated accounts.
        response = client.get(
            f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1/tradetwin-runs/{fx['run_id']}",
            headers={
                "Authorization": "Bearer " + tokens["driver-one"],
                "X-Organization-Id": fx["organizations"]["carrier"],
            },
        )
        assert response.status_code in {403, 404}
        assert not errors, errors
        browser.close()
        postman_checks(fx, tokens, fixture_file.parent)
    print(
        "PASS: authenticated Phase 5 comparison, desktop/mobile, masking, exact-hash approvals, "
        "carrier acceptance, atomic replacement, fresh Phase 4 handoff and evidence export"
    )


def postman_checks(fx, tokens, folder):
    executable = shutil.which("postman")
    if not executable:
        print("SKIP: optional Postman CLI is not installed", flush=True)
        return
    requests = []
    for name, path, role, side, expected, assertion in [
        (
            "Payer comparison",
            f"/tradetwin-runs/{fx['run_id']}",
            "seller-approver",
            "seller",
            200,
            "pm.expect(pm.response.json().price_visible).to.eql(true);",
        ),
        (
            "Price-masked comparison",
            f"/tradetwin-runs/{fx['run_id']}",
            "seller-operations",
            "seller",
            200,
            "pm.expect(pm.response.json()).not.to.have.property('rankings');",
        ),
        (
            "Driver comparison denied",
            f"/tradetwin-runs/{fx['run_id']}",
            "driver-one",
            "carrier",
            404,
            "pm.expect(pm.response.json()).not.to.have.property('candidates');",
        ),
    ]:
        requests.append(
            {
                "name": name,
                "request": {
                    "method": "GET",
                    "url": f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1{path}",
                    "header": [
                        {"key": "Authorization", "value": "Bearer " + tokens[role]},
                        {"key": "X-Organization-Id", "value": fx["organizations"][side]},
                    ],
                },
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                f"pm.test('Status', () => pm.response.to.have.status({expected}));",
                                "pm.test('Privacy boundary', () => {" + assertion + "});",
                            ],
                        },
                    }
                ],
            }
        )
    collection = folder / "postman-synthetic-checks.json"
    collection.write_text(
        json.dumps(
            {
                "info": {
                    "name": "Isolated synthetic Phase 5 acceptance",
                    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                },
                "item": requests,
            }
        ),
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                executable,
                "collection",
                "run",
                str(collection),
                "--no-report-events",
                "--disable-unicode",
                "--silent",
                "--timeout",
                "60000",
            ],
            capture_output=True,
            text=True,
            timeout=75,
        )
        if result.returncode:
            raise AssertionError("Local Postman privacy checks failed: " + result.stdout[-1200:])
        print("PASS: local Postman CLI comparison and price/driver privacy checks", flush=True)
    finally:
        collection.unlink(missing_ok=True)


def main():
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 3145)) == 0:
            raise SystemExit("Port 3145 occupied; refusing to replace an existing server")
    with ExitStack() as stack:
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-freight-")))
        key = base64.b64encode(secrets.token_bytes(32)).decode()
        smoke.start_local(
            stack,
            folder,
            {
                "PROFILE_AUTH_ENABLED": "true",
                "API_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['api']}",
                "APP_PUBLIC_URL": ORIGIN,
                "DOCUMENT_ENCRYPTION_KEY": key,
            },
        )
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+pysqlite:///{folder / 'shipment.db'}",
            "NEO4J_ENABLED": "false",
            "DOCUMENT_ENCRYPTION_KEY": key,
            "OPERATIONS_BROWSER_DATABASE_ROOT": str(folder),
        }
        seeded = subprocess.run(
            [sys.executable, "-m", "app.freight.cli"],
            cwd=ROOT / "services/shipment-service",
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        fx = json.loads(seeded.stdout)
        fixture_file = folder / "fixture.json"
        fixture_file.write_text(seeded.stdout, encoding="utf-8")
        tokens = {role: secrets.token_urlsafe(48) for role in fx["subjects"]}
        with closing(sqlite3.connect(folder / "api.db")) as db, db:
            for role, subject in fx["subjects"].items():
                db.execute(
                    "INSERT INTO auth_profiles VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        subject,
                        "https://test.invalid",
                        subject,
                        role + "@example.invalid",
                        role,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                db.execute(
                    "INSERT INTO auth_sessions VALUES (?, ?, ?)",
                    (
                        hashlib.sha256(tokens[role].encode()).hexdigest(),
                        subject,
                        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    ),
                )
        env.update({"PROFILE_AUTH_ENABLED": "true", "APP_PUBLIC_URL": ORIGIN})
        for name, port in smoke.SERVICES.items():
            env[f"{'API' if name == 'api' else name.upper()}_SERVICE_URL"] = (
                f"http://127.0.0.1:{port}"
            )
        log = stack.enter_context((folder / "web.log").open("w"))
        process = subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--port", "3145"],
            cwd=ROOT / "apps/web",
            env=env,
            stdout=log,
            stderr=log,
        )
        stack.callback(stop_process, process)
        for _ in range(80):
            try:
                httpx.get(ORIGIN + "/login", timeout=2).raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Browser fixture server did not start")
        exercise(fx, tokens, fixture_file, env)


if __name__ == "__main__":
    main()
