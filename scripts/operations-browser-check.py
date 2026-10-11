"""Authenticated Phase 2 lifecycle; sessions exist only in disposable test databases."""

import hashlib
import importlib.util
import json
import os
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
OUTPUT = ROOT / "artifacts/audit/operations"
spec = importlib.util.spec_from_file_location(
    "commercial_browser", ROOT / "scripts/commercial-browser-check.py"
)
commercial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commercial)
smoke = commercial.smoke


def run_browser(fixtures, tokens):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    trade_id = fixtures["trade_id"]
    operations = f"/shipments/trades/{trade_id}/operations"
    failures = []
    with httpx.Client(timeout=30) as client, sync_playwright() as playwright:

        def read(path, role="seller-operations", side="seller"):
            response = client.get(
                f"http://127.0.0.1:{smoke.SERVICES['shipment']}/api/v1{path}",
                headers={
                    "Authorization": f"Bearer {tokens[role]}",
                    "X-Organization-Id": fixtures["organizations"][side],
                },
            )
            response.raise_for_status()
            return response.json()

        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: failures.append(str(error)))

        def signin(role, path):
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
            if role != "unrelated":
                expect(page.get_by_text("SIMULATION", exact=True).first).to_be_visible()

        def submit(name):
            with page.expect_response(
                lambda r: r.request.method in {"POST", "PATCH", "PUT"} and "/api/services/" in r.url
            ) as pending:
                commercial.key_button(page, name)
            response = pending.value
            assert response.status in (200, 201), response.text()

        def scope(name):
            return page.locator("section").filter(
                has=page.get_by_role("heading", name=name, exact=True)
            )

        def upload_evidence(name, content, purpose, mime):
            page.get_by_label("Purpose", exact=True).select_option(purpose)
            page.get_by_label("Evidence file", exact=True).set_input_files(
                {"name": name, "mimeType": mime, "buffer": content}
            )
            with page.expect_response(
                lambda r: "/completions" in r.url and r.request.method == "POST"
            ) as pending:
                commercial.key_button(page, "Upload evidence")
            assert pending.value.status == 200, pending.value.text()
            completed = pending.value.json()
            assert completed["sha256"] == hashlib.sha256(content).hexdigest()
            assert completed["security_state"] == "QUARANTINED"
            expect(page.get_by_text(name, exact=True)).to_be_visible()
            article = page.locator("article").filter(has=page.get_by_text(name, exact=True))
            expect(article.get_by_text("Download blocked.", exact=False)).to_be_visible()
            expect(page.get_by_role("button", name="Download", exact=True)).to_have_count(0)
            return completed

        consignments = []
        for quantity in ("40", "60"):
            signin("seller-operations", f"/shipments/trades/{trade_id}/consignments/new")
            expect(
                page.get_by_role("heading", name="Allocate consignment", exact=True)
            ).to_be_visible()
            page.get_by_label("Allocate Cotton shirts", exact=True).fill(quantity)
            commercial.fill_fields(
                page,
                {
                    "pickup_contact_name": "Seller",
                    "pickup_contact_phone_e164": "+919876543210",
                    "delivery_contact_name": "Buyer",
                    "delivery_contact_phone_e164": "+919876543210",
                    "declared_gross_weight_kg": "400",
                    "package_count": 4,
                },
            )
            submit("Save draft reservation")
            expect(page).to_have_url(ORIGIN + operations)
            data = read(f"/trades/{trade_id}/operations")
            cn = next(
                c for c in data["consignments"] if c["id"] not in [x["id"] for x in consignments]
            )
            consignments.append(cn)
            article = page.locator("article").filter(has_text=cn["reference"]).first
            with page.expect_response(
                lambda r: "/preparations" in r.url and r.request.method == "POST"
            ) as pending:
                article.get_by_role("button", name="Prepare consignment", exact=True).click()
            assert pending.value.status == 200, pending.value.text()
            page.goto(ORIGIN + f"/shipments/consignments/{cn['id']}/assignment")
            expect(page.get_by_label("Carrier *", exact=True)).to_be_visible()
            page.get_by_label("Carrier *", exact=True).select_option(
                fixtures["organizations"]["carrier"]
            )
            submit("Propose assignment")

        assert (
            read(f"/trades/{trade_id}/operations")["availability"][0]["available_quantity"]
            == "0.000000"
        )
        for index, cn in enumerate(consignments):
            assignment_path = f"/shipments/consignments/{cn['id']}/assignment"
            signin("carrier-dispatcher", assignment_path)
            page.get_by_label("Owned vehicle *", exact=True).select_option(
                fixtures["vehicles"][index]
            )
            page.get_by_label("Active driver *", exact=True).select_option(
                fixtures["users"]["driver-one" if index == 0 else "driver-two"]
            )
            submit("Accept vehicle and driver assignment")
            current = read(f"/consignments/{cn['id']}")
            signin(
                "driver-one" if index == 0 else "driver-two",
                f"/shipments/tasks/{current['active_assignment_id']}",
            )
            page.set_viewport_size({"width": 390, "height": 844})
            commercial.fill_fields(
                page, {"actual_gross_weight_kg": "400", "actual_package_count": 4}
            )
            for name in ("Record Pickup Confirmed", "Record Departed", "Record Arrived"):
                submit(name)
                expect(page.get_by_role("button", name=name, exact=True)).to_have_count(0)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if index == 0:
                assert page.get_by_label("Consignment", exact=True).input_value() == cn["id"]
                uploaded = upload_evidence(
                    "pickup.pdf",
                    b"%PDF-1.4\n% pickup fixture\n%%EOF\n",
                    "PICKUP",
                    "application/pdf",
                )
                assert uploaded["consignment_id"] == cn["id"]
            page.screenshot(path=str(OUTPUT / f"driver-{index}-mobile.png"), full_page=True)
            signin("buyer-receiver", f"/shipments/consignments/{cn['id']}/receipt")
            for receipt_index, quantity in enumerate(["20", "20"] if index == 0 else ["60"]):
                form = scope("Record incremental receipt")
                form.get_by_label("Received quantity: Cotton shirts", exact=True).fill(quantity)
                submit("Record physical receipt")
                expect(page.get_by_text("Effective receipt", exact=True)).to_have_count(
                    receipt_index + 1
                )
            submit("Close delivery recording")
            expect(
                page.get_by_role("button", name="Reopen delivery recording", exact=True)
            ).to_be_visible()
            signin("buyer-inspector", f"/shipments/consignments/{cn['id']}/inspection")
            for article in scope("Independent inspection").locator("article").all():
                article.get_by_label("Accept quantity", exact=False).fill(
                    "20" if index == 0 else "60"
                )
                with page.expect_response(
                    lambda r: "/acceptances" in r.url and r.request.method == "POST"
                ) as pending:
                    article.get_by_role(
                        "button", name="Record inspection decision", exact=True
                    ).click()
                assert pending.value.status == 201, pending.value.text()
                expect(article.get_by_label("Accept quantity", exact=False)).to_have_value("0")

        payment_path = f"/shipments/trades/{trade_id}/payments"
        signin("buyer-finance", payment_path)
        submit("Propose goods schedule")
        submit("Approve exact schedule")
        signin("seller-finance", payment_path)
        submit("Approve exact schedule")
        signin("buyer-finance", payment_path)
        commercial.fill_fields(scope("Report outgoing payment"), {"amount_minor": "1000000"})
        submit("Report manual payment")
        expect(page.get_by_text("MANUAL_REPORTED", exact=True)).to_be_visible()
        signin("seller-finance", payment_path)
        submit("Acknowledge reported payment")
        obligation = read(f"/trades/{trade_id}/settlement", "seller-finance")["obligations"][0]
        page.get_by_label("Approved goods obligation *", exact=True).select_option(
            obligation["obligation_ref"]
        )
        page.get_by_label("Allocation amount (paise) *", exact=True).fill("1000000")
        submit("Allocate acknowledged funds")
        expect(page.get_by_text("FUNDED", exact=True)).to_be_visible()
        page.screenshot(path=str(OUTPUT / "payments-mobile.png"), full_page=True)
        signin("seller-finance", operations)
        commercial.key_button(page, "Documents")
        evidence_bytes = b"%PDF-1.4\n% isolated operational evidence fixture\n%%EOF\n"
        upload_evidence("manual-payment.pdf", evidence_bytes, "PAYMENT", "application/pdf")
        assert (
            read(f"/trades/{trade_id}/settlement", "seller-finance")["provider_verification"]
            == "NOT_ASSESSED"
        )
        for viewport in ({"width": 1440, "height": 1000}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            signin("seller-finance", operations)
            for module in (
                "Documents",
                "Compliance",
                "Graph",
                "Risk",
                "Optimizer",
                "Regulations",
                "Evidence",
                "Shipments",
            ):
                commercial.key_button(page, module)
                if module == "Graph":
                    expect(page.locator(".react-flow__node").first).to_be_visible()
                    assert page.locator(".react-flow__edge").count() > 0
                    total_nodes = page.locator(".react-flow__node").count()
                    page.get_by_label("Relationship scope", exact=True).select_option(
                        consignments[0]["id"]
                    )
                    page.wait_for_function(
                        "total => document.querySelectorAll('.react-flow__node').length < total",
                        arg=total_nodes,
                    )
                    node = page.locator(".react-flow__node").filter(
                        has_text=consignments[0]["reference"]
                    )
                    node.click()
                    expect(page.get_by_text("Incoming / Consignment", exact=True)).to_be_visible()
                    page.screenshot(
                        path=str(OUTPUT / f"graph-{viewport['width']}.png"), full_page=True
                    )
                if module == "Evidence":
                    expect(page.get_by_text("Payment Allocated", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), module
        signin("unrelated", operations)
        expect(page.get_by_text("Trade not found.", exact=True)).to_be_visible()
        result = read(f"/trades/{trade_id}/operations", "seller-finance")
        assert result["settlement"]["net_allocated_minor"] == "1000000"
        assert all(
            c["receipt_summary"][0]["inspection_status"] == "ACCEPTED"
            for c in result["consignments"]
        )
        assert not failures, failures
        browser.close()
    print(
        "PASS: authenticated 40/60 allocation, carrier consent, mobile drivers, 20+20/60 receipts, "
        "independent inspection, bilateral schedule, manual payment/ack/allocation, "
        "encrypted/quarantined evidence, eight panels and isolation"
    )


def main():
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 3133)) == 0:
            raise SystemExit("Port 3133 occupied; refusing to replace an existing server")
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-operations-"))
        )
        smoke.start_local(
            stack,
            folder,
            {
                "PROFILE_AUTH_ENABLED": "true",
                "API_SERVICE_URL": f"http://127.0.0.1:{smoke.SERVICES['api']}",
                "APP_PUBLIC_URL": ORIGIN,
                "EVIDENCE_CLAMAV_HOST": "",
            },
        )
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+pysqlite:///{folder / 'shipment.db'}",
            "NEO4J_ENABLED": "false",
            "OPERATIONAL_DEMO_ENABLED": "true",
        }
        seeded = subprocess.run(
            [sys.executable, "-m", "app.operations.cli"],
            cwd=ROOT / "services/shipment-service",
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        fixtures = json.loads(seeded.stdout)
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
        for name in smoke.SERVICES:
            env[f"{'API' if name == 'api' else name.upper()}_SERVICE_URL"] = (
                f"http://127.0.0.1:{smoke.SERVICES[name]}"
            )
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
        run_browser(fixtures, tokens)


if __name__ == "__main__":
    main()
