"""Browser verification against temporary domestic services and the built web app."""

import importlib.util
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts/smoke-test.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
SERVICE_OFFSET = int(os.environ.get("BROWSER_SERVICE_OFFSET", "10000"))
WEB_PORT = int(os.environ.get("BROWSER_WEB_PORT", "3104"))
smoke.SERVICES = {name: port + SERVICE_OFFSET for name, port in smoke.SERVICES.items()}
ORIGIN = f"http://localhost:{WEB_PORT}"


def browser_check():
    output = ROOT / "artifacts/audit/domestic"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(ORIGIN + "/dashboard/shipments/new")
        expect(page.get_by_role("heading", name="Create domestic shipment")).to_be_visible()
        page.get_by_label("Shipment reference", exact=True).fill("TT-BROWSER-DOMESTIC")
        page.get_by_label("Road carrier", exact=True).fill("Domestic Test Carrier")
        page.get_by_label("Consignor", exact=True).fill("Chennai Store")
        page.get_by_label("Consignee", exact=True).fill("Bengaluru Store")
        page.get_by_label("Planned departure", exact=True).fill("2026-09-14T09:00")
        page.get_by_label("Planned arrival", exact=True).fill("2026-09-15T09:00")
        page.get_by_label("GST-registered consignor", exact=True).select_option("yes")
        page.get_by_label("Ordinary taxable goods", exact=False).select_option("yes")
        page.get_by_label("Origin city", exact=True).fill("Chennai")
        page.get_by_label("Origin PIN code", exact=True).fill("600001")
        page.get_by_label("Stop 1 state", exact=True).select_option("Karnataka")
        page.get_by_label("Stop 1 city", exact=True).fill("Bengaluru")
        page.get_by_label("Stop 1 PIN code", exact=True).fill("560001")
        page.get_by_label("Distance from previous location (km)", exact=True).fill("350")
        page.get_by_label("Product", exact=True).fill("Cotton shirts")
        page.get_by_label("Description", exact=True).fill("Cotton shirts in cartons")
        page.get_by_label("Quantity", exact=True).fill("100")
        page.get_by_label("Consignment value incl. tax (INR)", exact=True).fill("75000")
        page.screenshot(path=str(output / "create-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0, 0)")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "create-mobile.png"), full_page=True)
        page.get_by_role("button", name="Create shipment", exact=True).click()
        expect(page).to_have_url(re.compile(r"/shipments/[a-z0-9-]+$"), timeout=15000)
        expect(page.get_by_text("TT-BROWSER-DOMESTIC", exact=True).first).to_be_visible()
        page.screenshot(path=str(output / "shipment-mobile.png"), full_page=True)
        page.goto(ORIGIN + "/")
        page.get_by_role("button", name="Load demo scenario", exact=True).click()
        expect(page).to_have_url(re.compile(r"/shipments/[a-z0-9-]+$"), timeout=15000)
        expect(page.get_by_text("TT-DEMO-TN-KA-MH", exact=True).first).to_be_visible()
        demo_url = page.url
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator("#graph").scroll_into_view_if_needed()
        page.wait_for_function("""() => {
            const frame = document.querySelector('.react-flow').getBoundingClientRect();
            const nodes = [...document.querySelectorAll('.react-flow__node')];
            return nodes.length > 0 && nodes.every(node => {
                const box = node.getBoundingClientRect();
                return box.left >= frame.left && box.right <= frame.right &&
                    box.top >= frame.top && box.bottom <= frame.bottom;
            });
        }""")
        page.screenshot(path=str(output / "graph-desktop.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.goto(ORIGIN + "/dashboard/regulations")
        expect(page.get_by_role("heading", name="Regulatory source review")).to_be_visible()
        expect(page.get_by_text("Demo catalog active.", exact=False)).to_be_visible()
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / f"regulatory-sources-{width}.png"), full_page=True)
        page.goto(demo_url + "/route-memory")
        expect(page.get_by_role("heading", name="Route memory and decisions")).to_be_visible()
        page.get_by_text("Add reviewed carrier offer", exact=True).click()
        for label, value in {
            "Carrier": "Browser Test Carrier",
            "Quote reference": "BROWSER-QUOTE-1",
            "All-inclusive price (INR)": "12000",
            "Carrier duration (hours)": "30",
            "Quote observed at": (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "Valid until departure / booking": (datetime.now() + timedelta(days=7)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "Quote source URL": "https://example.com/test-quote",
            "Source document reference": "Fixture quote only",
            "Gross weight (tonnes)": "12",
            "Height (m)": "3",
            "Width (m)": "2.5",
            "Length (m)": "8",
            "Axle load (tonnes)": "6",
            "Review rationale": "Browser fixture only; no real carrier price or legal assertion.",
        }.items():
            page.get_by_label(label, exact=True).fill(value)
        page.get_by_role("button", name="Save offer version").click()
        expect(page.get_by_text("Versioned offer saved.", exact=False)).to_be_visible()
        page.get_by_role("button", name="Compare current offers").click()
        expect(page.get_by_text("No booking-ready offer", exact=True)).to_be_visible()
        page.get_by_text("Add reviewed carrier offer", exact=True).click()
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
            page.screenshot(path=str(output / f"route-memory-{width}.png"), full_page=True)
        browser.close()
    print("PASS: domestic browser creation, mobile form, demo navigation and graph")


if __name__ == "__main__":
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", WEB_PORT)) != 0, "Web port is occupied"
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tt-domestic-browser-"))
        )
        smoke.start_local(stack, folder)
        env = {**os.environ, "PROFILE_AUTH_ENABLED": "false", "APP_PUBLIC_URL": ORIGIN}
        for service, key in [
            ("api", "API_SERVICE_URL"),
            ("shipment", "SHIPMENT_SERVICE_URL"),
            ("compliance", "COMPLIANCE_SERVICE_URL"),
            ("document", "DOCUMENT_SERVICE_URL"),
            ("intelligence", "INTELLIGENCE_SERVICE_URL"),
        ]:
            env[key] = f"http://127.0.0.1:{smoke.SERVICES[service]}"
        log = stack.enter_context((folder / "web.log").open("w"))
        child = subprocess.Popen(
            [
                "node",
                "node_modules/next/dist/bin/next",
                "start",
                "--port",
                str(WEB_PORT),
                "--hostname",
                "127.0.0.1",
            ],
            cwd=ROOT / "apps/web",
            env=env,
            stdout=log,
            stderr=log,
        )

        def stop():
            child.terminate()
            child.wait(timeout=15)

        stack.callback(stop)
        for _ in range(60):
            try:
                if httpx.get(ORIGIN + "/login", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        if "--preview" in sys.argv:
            print(f"Isolated domestic preview: {ORIGIN} (temporary demo data)", flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            browser_check()
