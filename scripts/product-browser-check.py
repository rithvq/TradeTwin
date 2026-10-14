"""Synthetic authenticated product acceptance, built on the existing isolated freight harness."""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/audit/product"
spec = importlib.util.spec_from_file_location(
    "freight_browser", ROOT / "scripts/freight-browser-check.py"
)
freight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freight)
baseline = freight.exercise


def exercise(fx, tokens, fixture_file, env):
    baseline(fx, tokens, fixture_file, env)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{freight.smoke.SERVICES['shipment']}/api/v1"
    headers = {
        "Authorization": "Bearer " + tokens["seller-operations"],
        "X-Organization-Id": fx["organizations"]["seller"],
    }
    with httpx.Client(timeout=30) as client:
        me = client.get(base_url + "/me", headers=headers).json()
        member = next(
            m for m in me["memberships"] if m["organization_id"] == fx["organizations"]["seller"]
        )
        response = client.post(
            base_url + f"/organizations/{member['organization_id']}/members",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={
                "user_id": me["user"]["id"],
                "capabilities": sorted(
                    set(member["capabilities"])
                    | {"EVIDENCE_ANALYST", "READINESS_OPERATOR", "DEMO_PRESENTER"}
                ),
            },
        )
        response.raise_for_status()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chromium"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(30000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.context.add_cookies(
            [
                {
                    "name": "tt_session",
                    "value": tokens["seller-operations"],
                    "url": freight.ORIGIN,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page.goto(freight.ORIGIN + f"/shipments/trades/{fx['trade_id']}/operations?module=Evidence")
        expect(
            page.get_by_role("heading", name="Historical decision replay", exact=True)
        ).to_be_visible()
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/evidence/replay-requests")
        ) as pending:
            page.get_by_role("button", name="Recompute captured inputs", exact=True).click()
        response = pending.value
        assert response.status == 202, response.text()
        requested = response.json()
        with httpx.Client(timeout=30) as client:
            job = client.get(
                base_url + "/evidence/replay-results/" + requested["id"], headers=headers
            )
            job.raise_for_status()
        # Use the request's existing job, not a new unrestricted evaluation pathway.
        lookup = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.product.cli",
                "--replay-request-id",
                requested["id"],
            ],
            cwd=ROOT / "services/shipment-service",
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "completed" in lookup.stdout
        section = page.get_by_role("region", name="Historical decision replay")
        expect(section.get_by_text(re.compile("^Match$", re.I))).to_be_visible()
        expect(section.get_by_text("Not assessed by replay", exact=True)).to_be_visible()
        page.screenshot(path=str(OUTPUT / "replay-desktop.png"), full_page=True)
        page.goto(freight.ORIGIN + "/dashboard/regulations/assurance")
        expect(page.get_by_role("heading", name="Deployment assurance", exact=True)).to_be_visible()
        expect(page.get_by_text(re.compile("Configure an external generation"))).to_be_visible()
        assert page.get_by_role("button", name=re.compile("activate|force", re.I)).count() == 0
        page.goto(freight.ORIGIN + "/dashboard/evidence/demonstration")
        page.get_by_role("button", name="Create simulation workspace", exact=True).click()
        page.get_by_role("button", name="Start registered demo", exact=True).click()
        page.get_by_role("button", name="Create Simulation Draft", exact=True).click()
        expect(
            page.get_by_role("link", name="Open ordinary commercial workspace", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Read Independent Dimensions", exact=True).click()
        page.get_by_role("button", name="Executable Recovery", exact=True).click()
        expect(page.get_by_role("status")).to_have_text("Blocked")
        for width in (1440, 360):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUTPUT / f"demo-{width}.png"), full_page=True)
        page.get_by_role("button", name="Create fresh successor", exact=True).click()
        expect(page.get_by_role("button", name="Start registered demo", exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()
    print(
        "PASS: synthetic replay, bounded demo, preserved successor history, desktop/360px",
        flush=True,
    )


if __name__ == "__main__":
    freight.exercise = exercise
    freight.main()
