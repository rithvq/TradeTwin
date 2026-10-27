"""Map UI acceptance on synthetic HTTP fixtures; no real profiles or trade data."""

import base64
import json
import os
import socket
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import httpx
from local_processes import stop_process
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:3152"
OUTPUT = ROOT / "artifacts/audit/freight-map"
# A single opaque test pixel makes CI independent of an external tile service.
# Opt in to real tiles for visual inspection; never cache or bulk-download them.
TEST_TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def fixtures():
    candidates = []
    for index in range(2):
        candidates.append(
            {
                "id": f"route-{index}",
                "label": "Synthetic route",
                "geometry_kind": "TOPOLOGICAL_SCHEMATIC",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [77.5946, 12.9716],
                        [78.3, 12.8 + index * 0.4],
                        [80.2707, 13.0827],
                    ],
                },
                "distance_m": 360000 + index * 40000,
                "driving_seconds": 21600 - index * 3600,
                "major_road_metres": None,
                "toll_road_metres": None,
                "road_names": [],
                "feasibility": "CONDITIONAL",
                "reason_codes": [],
                "metrics": {},
                "nominal_arrival_at": "2030-01-01T08:00:00Z",
                "estimated_arrival_at": None,
                "historic_adjusted_arrival_at": None,
                "state_requirements": [],
                "incident_impacts": [],
                "corridor": {
                    "state_sequence": ["29", "33"],
                    "state_names": ["Karnataka", "Tamil Nadu"],
                    "state_outlines": [],
                    "mapping_status": "RETAINED_TOPOLOGY",
                    "boundaries": {"name": "Simulation", "status": "RETAINED_REFERENCE"},
                },
                "history": {
                    "status": "INSUFFICIENT_HISTORY",
                    "sample_count": 0,
                    "median_extra_seconds": None,
                    "basis": "Simulation",
                },
                "weather": {"status": "NOT_REQUESTED", "exposure": None, "samples": []},
                "provider": {
                    "name": "Simulation",
                    "attribution": "TradeTwin simulation",
                    "traffic": "NOT_LIVE",
                },
            }
        )
    study = {
        "id": "map-study",
        "consignment_id": "cn",
        "job_state": "COMPLETED",
        "freshness": "CURRENT",
        "source_mode": "RETAINED",
        "execution_mode": "SIMULATION",
        "price_visible": False,
        "checked_at": "2030-01-01T00:00:00Z",
        "valid_until": "2030-01-01T00:15:00Z",
        "result": {
            "candidates": candidates,
            "weights": {},
            "comparison": {
                "best_candidate_id": "route-0",
                "comparison_status": "CONDITIONAL",
                "active_factors": [],
                "omitted_factors": [],
                "rankings": [],
            },
            "provider_failures": [],
            "policy_sources": [],
            "policy_packs": [],
            "limitations": [],
        },
    }
    return {
        "demo-sessions/map-check": {
            "id": "map-check",
            "status": "READY",
            "execution_mode": "SIMULATION",
            "expires_at": "2030-01-01T00:00:00Z",
            "expired": False,
            "trade_id": "trade",
            "organization_id": "demo-org",
            "consignment_id": "cn",
            "next_step_index": 0,
            "steps": [],
            "receipts": [],
            "route_study_ids": ["map-study"],
            "sample_document_version_id": None,
            "limitations": ["Browser test simulation"],
        },
        "me": {
            "user": {"id": "test", "display_name": "Map test", "email": "map@example.invalid"},
            "memberships": [
                {
                    "organization_id": "demo-org",
                    "legal_name": "Map test simulation",
                    "profile_status": "COMPLETE",
                    "capabilities": ["SELLER_DEMO_EXPLORER"],
                    "permissions": [],
                    "registrations": [],
                }
            ],
        },
        "reference-data": {
            "states": {"29": "Karnataka", "33": "Tamil Nadu"},
            "unit_codes": ["NOS"],
            "capability_permissions": {},
        },
        "freight-route-studies/map-study": study,
    }


def exercise():
    data = fixtures()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chromium"), headless=True
        )
        errors = []
        for offline in [False, True]:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(30000)
            page.on("pageerror", lambda error: errors.append(str(error)))

            def respond(route):
                resource = route.request.url.split("/api/v1/", 1)[1]
                if resource not in data:
                    raise AssertionError("Unexpected test API request: " + resource)
                route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(data[resource])
                )

            page.route("**/api/services/shipment/api/v1/**", respond)
            if offline:
                page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
            elif os.getenv("FREIGHT_MAP_LIVE_TILES") != "true":
                page.route(
                    "https://tile.openstreetmap.org/**",
                    lambda route: route.fulfill(content_type="image/png", body=TEST_TILE),
                )

            def settle_tiles(page=page, offline=offline):
                page.wait_for_function(
                    """() => [...document.querySelectorAll('.leaflet-tile')].length &&
                    [...document.querySelectorAll('.leaflet-tile')].every(img => img.complete) ||
                    [...document.querySelectorAll('[role=status]')].some(
                      node => node.textContent.includes('Road tiles unavailable'))"""
                )
                if not offline and os.getenv("FREIGHT_MAP_LIVE_TILES") != "true":
                    assert page.locator(".leaflet-tile-loaded").count() > 0
                page.mouse.move(0, 0)

            page.goto(ORIGIN + "/demo/map-check")
            figure = page.get_by_role("region", name="India freight route map", exact=True)
            expect(figure.locator(".leaflet-container")).to_be_visible()
            expect(figure.get_by_role("button", name="Show routes across India")).to_be_visible()
            expect(figure.get_by_text("Pickup · Karnataka", exact=True)).to_be_visible()
            expect(figure.get_by_text("Delivery · Tamil Nadu", exact=True)).to_be_visible()
            expect(figure.locator(".leaflet-control-attribution")).to_contain_text("OpenStreetMap")
            if offline:
                expect(
                    figure.get_by_text(
                        "Road tiles unavailable. Showing the India state reference.", exact=True
                    )
                ).to_be_visible()
                assert figure.locator(".leaflet-overlay-pane path").count() >= 36
            else:
                # Wait for actual street tiles, not just the Leaflet container.
                settle_tiles()
            figure.screenshot(
                path=str(OUTPUT / f"regional-{'offline' if offline else 'online'}.png")
            )
            figure.get_by_role("button", name="All India", exact=True).click()
            expect(figure.get_by_role("button", name="All India", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
            settle_tiles()
            figure.screenshot(path=str(OUTPUT / f"india-{'offline' if offline else 'online'}.png"))
            figure.get_by_role("button", name="Fit routes", exact=True).click()
            figure.get_by_role("button", name="Zoom in", exact=True).click()
            figure.get_by_role("button", name="Zoom out", exact=True).click()
            figure.get_by_role("button", name="Route 2", exact=True).click()
            expect(figure.get_by_role("button", name="Route 2", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
            for width in [390, 1440]:
                page.set_viewport_size({"width": width, "height": 1000})
                figure.get_by_role("button", name="Fit routes", exact=True).click()
                settle_tiles()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                figure.screenshot(
                    path=str(OUTPUT / f"selected-{width}-{'offline' if offline else 'online'}.png")
                )
                for label in ["Pickup · Karnataka", "Delivery · Tamil Nadu"]:
                    expect(figure.get_by_text(label, exact=True)).to_have_count(1)
                    bounds = figure.get_by_text(label, exact=True).bounding_box()
                    frame = figure.bounding_box()
                    assert bounds and frame
                    assert bounds["x"] >= frame["x"], (label, width, bounds, frame)
                    assert bounds["x"] + bounds["width"] <= frame["x"] + frame["width"], (
                        label,
                        width,
                        bounds,
                        frame,
                    )
            context.close()
            mode = "offline state map" if offline else "online geographic map"
            print(
                f"PASS: {mode}, India overview, selection, zoom controls and mobile",
                flush=True,
            )
        assert not errors, errors
        browser.close()


def main():
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 3152)) == 0:
            raise RuntimeError("Port 3152 is occupied; refusing to replace another server")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        folder = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-map-check-"))
        )
        log = stack.enter_context((folder / "web.log").open("w+"))
        server = subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--port", "3152"],
            cwd=ROOT / "apps/web",
            env={**os.environ, "PROFILE_AUTH_ENABLED": "false"},
            stdout=log,
            stderr=log,
        )
        stack.callback(stop_process, server)
        for _ in range(80):
            try:
                httpx.get(ORIGIN + "/login", timeout=1).raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.25)
        exercise()


if __name__ == "__main__":
    main()
