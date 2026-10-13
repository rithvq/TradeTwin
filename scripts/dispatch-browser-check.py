"""Authenticated release chain against disposable services and encrypted real files."""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "document_browser", ROOT / "scripts/document-browser-check.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
ORIGIN = harness.ORIGIN
OUTPUT = ROOT / "artifacts/audit/dispatch"


def postman_smoke(fx, tokens):
    cli = shutil.which("postman")
    if not cli:
        raise RuntimeError("Postman CLI is required when RUN_POSTMAN_SMOKE=true")
    with tempfile.TemporaryDirectory(prefix="tradetwin-postman-local-") as folder:
        environment = Path(folder) / "ephemeral-environment.json"
        values = {
            "base_url": f"http://127.0.0.1:{harness.smoke.SERVICES['shipment']}",
            "consignment_id": fx["consignment_id"],
            "action": "DEPARTED",
            "preparer_org": fx["organizations"]["seller"],
            "preparer_token": tokens["seller-operations"],
        }
        environment.write_text(
            json.dumps(
                {
                    "name": "Disposable local test only",
                    "values": [{"key": k, "value": v, "enabled": True} for k, v in values.items()],
                }
            )
        )
        completed = subprocess.run(
            [
                cli,
                "collection",
                "run",
                str(ROOT / "docs/postman/guarded-dispatch.postman_collection.json"),
                "-e",
                str(environment),
                "-i",
                "Read-only smoke",
                "--no-report-events",
                "--bail",
                "--timeout-request",
                "10000",
                "--disable-unicode",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("Local Postman read-only checks failed: " + completed.stdout)
        print("PASS: Postman CLI read-only checks; run reporting disabled, credentials discarded.")


def exercise(fx, tokens):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cn_id, trade_id = fx["consignment_id"], fx["trade_id"]
    operations = f"/shipments/trades/{trade_id}/operations"
    failures = []
    with httpx.Client(timeout=40) as client, sync_playwright() as playwright:

        def request(method, path, data=None, role="seller-operations", etag=None):
            side = (
                "carrier"
                if role.startswith(("carrier", "driver"))
                else "buyer"
                if role.startswith("buyer")
                else "seller"
            )
            headers = {
                "Authorization": f"Bearer {tokens[role]}",
                "X-Organization-Id": fx["organizations"][side],
                "Idempotency-Key": str(uuid4()),
            }
            if etag:
                headers["If-Match"] = etag
            response = client.request(
                method,
                f"http://127.0.0.1:{harness.smoke.SERVICES['shipment']}/api/v1{path}",
                headers=headers,
                json=data,
            )
            assert response.status_code in {200, 201, 202}, response.text()
            return response.json()

        def wait(action):
            for _ in range(160):
                state = request("GET", f"/consignments/{cn_id}/dispatch-readiness?action={action}")
                if state["evaluation"] and state["evaluation"]["job_state"] not in {
                    "QUEUED",
                    "RUNNING",
                }:
                    return state
                time.sleep(0.25)
            raise AssertionError("Compliance worker did not complete its durable job")

        def evaluate(action):
            ctx = request("GET", f"/consignments/{cn_id}/compliance-context")
            request(
                "POST",
                f"/consignments/{cn_id}/compliance-evaluations",
                {"action": action, "expected_context_version": ctx["context_version"]},
                etag=ctx["etag"],
            )
            return wait(action)

        ctx = request("GET", f"/consignments/{cn_id}/compliance-context")
        request("GET", f"/trades/{trade_id}/document-assessment-summary")
        invoice = next(d for d in ctx["documents"] if d["document_type"] == "TAX_INVOICE")
        ewb = next(d for d in ctx["documents"] if d["document_type"] == "EWAY_BILL_COPY")
        basis = {
            "compliance_fact_revision_id": ctx["heads"]["current_fact_revision_id"],
            "loading_manifest_revision_id": ctx["heads"]["current_loading_manifest_revision_id"],
            "seller_turnover_declaration_id": ctx["effective_facts"][
                "seller_turnover_declaration_id"
            ],
            "movement_document": invoice["reference"],
            "supporting_documents": [],
            "verification_result_ids": [r["id"] for r in invoice["verification_results"]],
            "transport_evidence_revision_ids": [r["id"] for r in ctx["transport_evidence"]],
        }

        def bind(body):
            current = request("GET", f"/consignments/{cn_id}/compliance-context")
            return request(
                "POST",
                f"/consignments/{cn_id}/compliance-evidence-binding-revisions",
                {"expected_context_version": current["context_version"], "bindings": body},
                etag=current["etag"],
            )

        bind(basis)
        blocked = evaluate("PICKUP_CONFIRMED")
        assert blocked["state"] == "BLOCKED"
        assert any(
            r["requirement_code"] == "EWB_REQUIRED" and r["outcome"] == "FAILED"
            for r in blocked["evaluation"]["requirements"]
        )
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on(
            "response",
            lambda response: failures.append(
                f"HTTP {response.status}: {response.url.split('?')[0]}"
            )
            if response.status >= 500
            else None,
        )

        def signin(role, path=operations):
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

        def module(name):
            harness.commercial.key_button(page, name)

        def section(name):
            return (
                page.locator("section")
                .filter(has=page.get_by_role("heading", name=name, exact=True))
                .last
            )

        def submit(name, target=None):
            with page.expect_response(
                lambda r: r.request.method == "POST" and "/api/services/" in r.url
            ) as pending:
                (target or page).get_by_role("button", name=name, exact=True).click()
            assert pending.value.status in {200, 201, 202}, pending.value.text()
            return pending.value.json()

        signin("seller-operations")
        module("Compliance")
        expect(
            section("Versioned requirements").get_by_text("EWB_REQUIRED", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Approve platform release", exact=True)
        ).to_have_count(0)
        page.screenshot(path=str(OUTPUT / "missing-ewb-desktop.png"), full_page=True)
        basis["supporting_documents"] = [ewb["reference"]]
        basis["verification_result_ids"] += [r["id"] for r in ewb["verification_results"]]
        bind(basis)
        assert evaluate("PICKUP_CONFIRMED")["state"] == "ELIGIBLE_FOR_REVIEW"

        authorisations = []
        for action in ("PICKUP_CONFIRMED", "DEPARTED"):
            if action == "DEPARTED":
                assert evaluate(action)["state"] == "ELIGIBLE_FOR_REVIEW"
            signin("seller-approver")
            module("Compliance")
            page.get_by_role(
                "button", name="Departure" if action == "DEPARTED" else "Pickup", exact=True
            ).click()
            release = section("Versioned requirements")
            expect(
                release.get_by_role("button", name="Approve platform release", exact=True)
            ).to_be_visible()
            release.get_by_label("Reason *", exact=True).first.fill(
                "Independent exact-hash simulation review"
            )
            submit("Approve platform release", release)
            signin("carrier-dispatcher", f"/shipments/consignments/{cn_id}/assignment")
            page.get_by_role(
                "button", name="Departure" if action == "DEPARTED" else "Pickup", exact=True
            ).click()
            packet_form = section("Dispatch packet")
            expect(packet_form.locator("select").first).to_be_visible()
            packet_form.locator("select").nth(0).select_option(
                invoice["assets"][0]["attachment_id"]
            )
            packet_form.locator("select").nth(1).select_option("EWB_NUMBER")
            prepared = submit("Prepare exact dispatch packet", packet_form)
            assignment_id = prepared["assignment_id"]
            signin("driver-one", f"/shipments/tasks/{assignment_id}")
            page.set_viewport_size({"width": 390, "height": 844})
            driver_packet = section("Prepared carried-document packet")
            expect(driver_packet.get_by_text("INVOICE_COPY", exact=False)).to_be_visible()
            expect(driver_packet.get_by_text("EWB_NUMBER", exact=False).first).to_be_visible()
            with page.expect_download() as downloaded:
                with page.expect_response(
                    lambda r: "/items/" in r.url and r.url.endswith("/download")
                ) as grant:
                    driver_packet.get_by_role(
                        "button", name="Prepare offline copy", exact=True
                    ).click()
                assert grant.value.status == 200, grant.value.text()
            downloaded.value.save_as(OUTPUT / f"{action}-SIMULATION-invoice.pdf")
            assert (OUTPUT / f"{action}-SIMULATION-invoice.pdf").read_bytes().startswith(b"%PDF-")
            driver_packet.get_by_role("checkbox").check()
            submit("Acknowledge exact packet", driver_packet)
            signin("carrier-dispatcher", f"/shipments/consignments/{cn_id}/assignment")
            page.get_by_role(
                "button", name="Departure" if action == "DEPARTED" else "Pickup", exact=True
            ).click()
            token = submit("Request platform dispatch authorisation", section("Dispatch packet"))
            authorisations.append(token["authorisation_id"])
            signin("driver-one", f"/shipments/tasks/{assignment_id}")
            if action == "PICKUP_CONFIRMED":
                expect(page.locator('[id$="-actual_gross_weight_kg"]')).to_be_visible()
                harness.commercial.fill_fields(
                    page, {"actual_gross_weight_kg": "400", "actual_package_count": 4}
                )
            button = (
                "Record Pickup Confirmed" if action == "PICKUP_CONFIRMED" else "Record Departed"
            )
            expect(page.get_by_role("button", name=button, exact=True)).to_be_enabled()
            submit(button)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUTPUT / f"{action}-mobile.png"), full_page=True)

        assert len(set(authorisations)) == 2
        for token in authorisations:
            ledger = request("GET", f"/dispatch-authorizations/{token}/evidence-manifest")
            assert ledger["dispatch"]["consumed_event_id"]
            assert ledger["manifest_hash"] and "pan_aggregate_turnover_minor" not in json.dumps(
                ledger
            )
        signin("seller-operations")
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
            module("Graph")
            graph = page.get_by_label("Compliance evidence provenance graph", exact=True)
            expect(graph.locator(".react-flow__node").first).to_be_visible()
            assert graph.locator(".react-flow__edge").count() > 0
            page.screenshot(path=str(OUTPUT / f"evidence-graph-{width}.png"), full_page=True)
            graph.screenshot(path=str(OUTPUT / f"provenance-{width}.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        constraints = request(
            "GET", f"/consignments/{cn_id}/compliance-constraints?action=DEPARTED"
        )
        assert constraints["evaluation_hash"] and constraints["dependency_hash"]
        assert constraints["freshness"] == "STALE"  # Actual movement changed the factual context.
        assert not failures, failures
        expect(page.locator("main").get_by_role("alert")).to_have_count(0)
        if os.getenv("RUN_POSTMAN_SMOKE") == "true":
            postman_smoke(fx, tokens)
        browser.close()
    print(
        "PASS: explained EWB blocker, encrypted packet download, independent review, "
        "carrier packet, "
        "driver ACK, distinct atomic pickup/departure, immutable evidence and mobile graph. "
        "SIMULATION statuses/signatures and ClamAV transport fixture only."
    )


if __name__ == "__main__":
    harness.main(seed_module="app.compliance.cli", exercise_fn=exercise)
