"""Check browser login boundaries against isolated services and a built Next.js frontend."""

import hashlib
import importlib.util
import os
import secrets
import socket
import sqlite3
import subprocess
import tempfile
import time
from contextlib import ExitStack, closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "security_check", ROOT / "scripts/profile-security-check.py"
)
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)
security.PUBLIC_ORIGIN = "http://localhost:3120"
OUTPUT = ROOT / "artifacts/audit/login"


def run_browser(folder):
    token = secrets.token_urlsafe(48)
    with closing(sqlite3.connect(folder / "api.db")) as db, db:
        db.execute(
            "INSERT INTO auth_sessions VALUES (?, ?, ?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                "alice",
                (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            ),
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://localhost:3120/dashboard")
        expect(page).to_have_url("http://localhost:3120/login")
        expect(page.get_by_role("button", name="Sign-in not configured")).to_be_disabled()
        page.screenshot(path=str(OUTPUT / "login-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / "login-mobile.png"))
        assert (
            page.request.get("http://localhost:3120/api/services/shipment/shipments").status == 401
        )
        page.context.add_cookies(
            [
                {
                    "name": "tt_session",
                    "value": token,
                    "url": "http://localhost:3120",
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page.goto("http://localhost:3120/dashboard")
        expect(page).to_have_url("http://localhost:3120/dashboard")
        page.get_by_role("button", name="Open user menu").click()
        expect(page.get_by_role("heading", name="alice", exact=True)).to_be_visible()
        page.screenshot(path=str(OUTPUT / "profile-mobile.png"))
        response = page.request.get("http://localhost:3120/api/services/shipment/shipments")
        assert response.status == 200 and len(response.json()) == 1
        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(page).to_have_url("http://localhost:3120/login")
        page.goto("http://localhost:3120/dashboard")
        expect(page).to_have_url("http://localhost:3120/login")
        browser.close()
    print("PASS: login gate, private session profile, logout, desktop and mobile login layouts")


if __name__ == "__main__":
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", 3120)) != 0, "Port 3120 is already occupied"
    with ExitStack() as stack:
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-login-")))
        security.smoke.start_local(
            stack,
            folder,
            {
                "PROFILE_AUTH_ENABLED": "true",
                "API_SERVICE_URL": "http://127.0.0.1:19000",
                "APP_PUBLIC_URL": security.PUBLIC_ORIGIN,
            },
        )
        security.exercise(folder)
        env = {
            **os.environ,
            "PROFILE_AUTH_ENABLED": "true",
            "APP_PUBLIC_URL": security.PUBLIC_ORIGIN,
        }
        for name, variable in [
            ("api", "API_SERVICE_URL"),
            ("shipment", "SHIPMENT_SERVICE_URL"),
            ("compliance", "COMPLIANCE_SERVICE_URL"),
            ("document", "DOCUMENT_SERVICE_URL"),
            ("intelligence", "INTELLIGENCE_SERVICE_URL"),
        ]:
            env[variable] = f"http://127.0.0.1:{security.smoke.SERVICES[name]}"
        log = stack.enter_context((folder / "web.log").open("w"))
        child = subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--port", "3120"],
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
                if httpx.get("http://localhost:3120/login", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        run_browser(folder)
