"""Browser checks against the isolated audit UI (start it on port 3100)."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "artifacts" / "audit"
OUTPUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.goto("http://127.0.0.1:3100/dashboard")
    expect(page.get_by_role("button", name="Open Shipment Twin details")).to_be_visible()
    page.screenshot(path=str(OUTPUT / "dashboard-desktop.png"))
    page.get_by_role("button", name="TradeTwin Demo", exact=True).click()
    page.wait_for_url("**/shipments/*")
    expect(page.get_by_role("heading", name="Consignment List", exact=True)).to_be_visible()
    shipment_url = page.url
    page.get_by_role("button", name="Evaluate uploaded evidence", exact=True).click()
    expect(page.get_by_text("Last assessment:", exact=False)).to_be_visible()
    page.get_by_role("button", name="Recommend", exact=True).first.click()
    expect(page.get_by_text("850760 - Lithium-ion accumulators", exact=True)).to_be_visible()
    page.get_by_role("button", name="Generate risk score", exact=True).click()
    expect(page.get_by_text("Model: synthetic-demo-v1", exact=False)).to_be_visible()
    page.get_by_role("button", name="Compare routes", exact=True).click()
    expect(page.get_by_role("heading", name="Current route", exact=True)).to_be_visible()
    with page.expect_download() as report:
        page.get_by_role("button", name="PDF", exact=True).click()
    assert report.value.suggested_filename.endswith(".pdf")
    page.locator("#graph").scroll_into_view_if_needed()
    expect(page.locator(".react-flow__node").first).to_be_visible()
    page.screenshot(path=str(OUTPUT / "shipment-graph-desktop.png"))
    for module in [
        "shipments",
        "documents",
        "compliance",
        "graph",
        "risk",
        "optimizer",
        "regulations",
        "evidence",
        "reports",
    ]:
        page.goto(f"http://127.0.0.1:3100/dashboard/{module}")
        expect(page.get_by_role("heading", name="Choose a shipment")).to_be_visible()
        expect(page.get_by_text("TT-DEMO-IND-UAE-DEU", exact=True)).to_be_visible()
    page.goto(shipment_url + "/documents")
    expect(page.get_by_role("button", name="Upload document", exact=True)).to_be_visible()
    page.get_by_label("File", exact=True).set_input_files(
        {
            "name": "browser-safety.txt",
            "mimeType": "text/plain",
            "buffer": (
                b"Document Number: BROWSER-001\nProduct Name: Lithium batteries\nQuantity: 120\n"
            ),
        }
    )
    page.get_by_role("button", name="Upload document", exact=True).click()
    expect(page.get_by_text("browser-safety.txt", exact=True)).to_be_visible()
    page.get_by_role("button", name="Extract metadata", exact=True).first.click()
    expect(page.get_by_text("BROWSER-001", exact=True).first).to_be_visible()
    expect(page.get_by_text("Last assessment:", exact=False)).to_be_visible()
    for width in [390, 768, 1440]:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto("http://127.0.0.1:3100/dashboard")
        page.screenshot(path=str(OUTPUT / f"dashboard-{width}.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            f"Dashboard overflow at {width}px"
        )
        page.goto(shipment_url)
        expect(page.get_by_role("heading", name="Consignment List", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            f"Shipment detail overflow at {width}px"
        )
        page.screenshot(path=str(OUTPUT / f"shipment-{width}.png"))
    assert not failures, failures
    browser.close()
    print("PASS: dashboard, demo launch, evaluation, graph, module pages and responsive layouts")
