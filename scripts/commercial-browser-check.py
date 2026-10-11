"""Real session cookies and full commercial UI against disposable local databases."""

import hashlib
import importlib.util
import json
import os
import re
import secrets
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
ORIGIN = "http://localhost:3133"
OUTPUT = ROOT / "artifacts/audit/commercial"
spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts/smoke-test.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
smoke.SERVICES = {name: port + 13000 for name, port in smoke.SERVICES.items()}


def key_button(page, name):
    button = page.get_by_role("button", name=name, exact=True)
    expect(button).to_be_enabled(timeout=15000)
    button.focus()
    button.press("Enter")


def flatten(values, prefix=""):
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from flatten(value, path)
        elif not isinstance(value, list):
            yield path, value


def fill_fields(scope, values):
    for path, value in flatten(values):
        control = scope.locator(f'[id$="-{path}"]')
        if not control.count() or value is None:
            continue
        kind = control.get_attribute("type")
        if kind == "checkbox":
            control.set_checked(bool(value))
        elif control.evaluate("element => element.tagName") == "SELECT":
            control.select_option(str(value))
        elif kind == "datetime-local":
            local = datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(minutes=330)
            control.fill(local.strftime("%Y-%m-%dT%H:%M"))
        else:
            control.fill(str(value))


def run_browser(folder, fixtures, tokens):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    seller = fixtures["organizations"]["seller"]
    with httpx.Client(timeout=30) as client:
        source = client.get(
            f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1/trades/{fixtures['trades']['DRAFT']}",
            headers={
                "Authorization": f"Bearer {tokens['seller-operator']}",
                "X-Organization-Id": seller,
            },
        ).json()
    facts = source["current_candidate_revision"]["facts"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(ORIGIN + "/trades")
        expect(page).to_have_url(ORIGIN + "/login")

        def signin(name, path):
            page.context.clear_cookies()
            page.context.add_cookies(
                [
                    {
                        "name": "tt_session",
                        "value": tokens[name],
                        "url": ORIGIN,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
            page.goto(ORIGIN + path)
            expect(page.get_by_role("heading", name="Trade workspace", exact=True)).to_be_visible()

        signin("seller-operator", "/trades/new")
        key_button(page, "Save and continue")
        expect(page.get_by_role("heading", name="Parties and billing", exact=True)).to_be_visible()
        page.get_by_label("Buyer organisation", exact=True).select_option(
            fixtures["organizations"]["buyer"]
        )
        fill_fields(page, facts)
        key_button(page, "Save and continue")
        expect(page.get_by_role("heading", name="Goods lines", exact=True)).to_be_visible()
        key_button(page, "Add goods line")
        for index, item in enumerate(facts["items"]):
            section = page.locator("section").filter(
                has=page.get_by_role("heading", name=f"Line {index + 1}", exact=True)
            )
            fill_fields(section, item)
        key_button(page, "Save and continue")
        expect(
            page.get_by_role("heading", name="Price and commercial terms", exact=True)
        ).to_be_visible()
        fill_fields(page, facts)
        key_button(page, "Save and continue")
        expect(page.get_by_role("heading", name="Dispatch address", exact=True)).to_be_visible()
        fill_fields(page, facts)
        key_button(page, "Save and continue")
        expect(
            page.get_by_role("heading", name="Candidate commercial terms", exact=True)
        ).to_be_visible()
        page.screenshot(path=str(OUTPUT / "review-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / "review-mobile.png"), full_page=True)
        key_button(page, "Save and continue")
        key_button(page, "Publish offer")
        expect(page).not_to_have_url(ORIGIN + "/trades/new", timeout=15000)
        path = page.url.removeprefix(ORIGIN)
        expect(page.get_by_text("Commercial agreement status: OFFERED", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Accept offered terms", exact=True)).to_have_count(0)
        for side in ("seller", "buyer"):
            signin(f"{side}-approver", path)
            page.get_by_label("I have reviewed", exact=False).check()
            key_button(page, "Accept offered terms")
            expected_status = "OFFERED" if side == "seller" else "CONFIRMED"
            expect(
                page.get_by_text(f"Commercial agreement status: {expected_status}", exact=True)
            ).to_be_visible()
        expect(
            page.get_by_role("heading", name="Accepted commercial agreement", exact=True)
        ).to_be_visible()
        original_hash = page.get_by_text("Terms hash:", exact=False).first.inner_text()
        signin("buyer-operator", path)
        page.get_by_label("Reason (required", exact=False).fill("Adjust order quantity")
        key_button(page, "Propose amendment")
        expect(
            page.get_by_role("heading", name="Pending amendment (not yet agreed)", exact=True)
        ).to_be_visible()
        expect(page.get_by_text(original_hash, exact=True).first).to_be_visible()
        page.get_by_role("link", name="Resume candidate", exact=True).focus()
        page.get_by_role("link", name="Resume candidate", exact=True).press("Enter")
        key_button(page, "3. Goods")
        page.get_by_label(re.compile(r"^Quantity")).first.fill("12.000000")
        key_button(page, "Save draft")
        expect(page.get_by_role("status").filter(has_text="Saved")).to_be_visible(timeout=15000)
        key_button(page, "7. Publish offer")
        key_button(page, "Publish offer")
        expect(page).to_have_url(ORIGIN + path, timeout=15000)
        for side in ("buyer", "seller"):
            signin(f"{side}-approver", path)
            page.get_by_label("I have reviewed", exact=False).check()
            key_button(page, "Accept offered terms")
            expect(
                page.get_by_role("button", name="Accept offered terms", exact=True)
            ).to_have_count(0)
        expect(page.get_by_text("12.000000", exact=False).first).to_be_visible()
        expect(page.get_by_text("Dispatch readiness: Not assessed", exact=True)).to_be_visible()
        key_button(page, "Evidence")
        expect(page.get_by_text("AMENDMENT ACCEPTED", exact=True)).to_be_visible()
        page.screenshot(path=str(OUTPUT / "evidence-mobile.png"), full_page=True)
        for module in ("Documents", "Compliance", "Graph", "Risk", "Optimizer", "Regulations"):
            key_button(page, module)
            expect(page.get_by_text("No shipment execution is linked", exact=False)).to_be_visible()
            expect(
                page.get_by_role("link", name=f"Open existing {module.lower()} module", exact=True)
            ).to_have_attribute("href", f"/dashboard/{module.lower()}")
        signin("unrelated", path)
        expect(page.get_by_text("Trade not found.", exact=True)).to_be_visible()
        assert not failures, failures
        browser.close()
    print(
        "PASS: real session gates, keyboard-operated create/publish/confirm/amend, "
        "mobile layout, evidence, eight module links and unrelated-party denial"
    )


def main():
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 3133)) == 0:
            raise SystemExit("Port 3133 is occupied; refusing to test an existing server")
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-commercial-"))
        )
        smoke.start_local(
            stack,
            folder,
            {
                "PROFILE_AUTH_ENABLED": "true",
                "API_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['api']}",
                "APP_PUBLIC_URL": ORIGIN,
            },
        )
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+pysqlite:///{folder / 'shipment.db'}",
            "NEO4J_ENABLED": "false",
        }
        result = subprocess.run(
            [sys.executable, "-m", "app.trades.cli"],
            cwd=ROOT / "services/shipment-service",
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        fixtures = json.loads(result.stdout)
        tokens = {name: secrets.token_urlsafe(48) for name in fixtures["subjects"]}
        with closing(sqlite3.connect(folder / "api.db")) as db, db:
            for name, subject in fixtures["subjects"].items():
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
        env.update({"PROFILE_AUTH_ENABLED": "true", "APP_PUBLIC_URL": ORIGIN})
        for name, variable in (
            ("api", "API_SERVICE_URL"),
            ("shipment", "SHIPMENT_SERVICE_URL"),
            ("compliance", "COMPLIANCE_SERVICE_URL"),
            ("document", "DOCUMENT_SERVICE_URL"),
            ("intelligence", "INTELLIGENCE_SERVICE_URL"),
        ):
            env[variable] = f"http://127.0.0.1:{smoke.SERVICES[name]}"
        log = stack.enter_context((folder / "web.log").open("w"))
        process = subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--port", "3133"],
            cwd=ROOT / "apps/web",
            env=env,
            stdout=log,
            stderr=log,
        )
        stack.callback(stop_process, process)
        for _ in range(100):
            try:
                if httpx.get(ORIGIN + "/login", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        run_browser(folder, fixtures, tokens)


if __name__ == "__main__":
    main()
