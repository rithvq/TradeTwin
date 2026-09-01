from __future__ import annotations

from html import escape
from io import BytesIO
from textwrap import wrap
from typing import Any

from app.schemas import ComplianceAssessmentRead, RouteOptimizationRead

LEGAL_DISCLAIMER = (
    "TradeTwin is a project prototype. Demo rules, classifications, risk scores, "
    "route recommendations, and reports are for evaluation only and are not legal, "
    "customs, tax, logistics, or regulatory advice."
)


def build_html_report(
    shipment: dict[str, Any],
    assessment: ComplianceAssessmentRead,
    evidence_records: list[dict[str, Any]],
    route_options: RouteOptimizationRead | None,
) -> str:
    recommended_route = (
        next((option for option in route_options.options if option.is_recommended), None)
        if route_options
        else None
    )
    consignment_rows = "".join(
        f"""
        <tr>
          <td>{escape(item["product_name"])}</td>
          <td>{escape(item["country_of_origin"])}</td>
          <td>{escape(item["destination_country"])}</td>
          <td>{escape(str(item["quantity"]))}</td>
          <td>{escape(str(item["declared_value"]))} {escape(item["currency"])}</td>
          <td>{escape(item["customs_status"])}</td>
        </tr>
        """
        for item in shipment.get("consignments", [])
    )
    rule_rows = "".join(
        f"""
        <tr>
          <td>{escape(rule.rule_id)}</td>
          <td>{escape(rule.title)}</td>
          <td>{escape(rule.jurisdiction)}</td>
          <td>{escape(rule.procedure_type)}</td>
          <td>{escape(rule.version)}</td>
          <td>{escape(rule.status)}</td>
          <td>{escape(", ".join(rule.missing_documents) or "None")}</td>
        </tr>
        """
        for rule in assessment.result.applicable_rules
    )
    evidence_items = "".join(
        f"<li><strong>{escape(record.get('evidence_type', 'EVIDENCE'))}</strong>: "
        f"{escape(record.get('explanation', ''))}</li>"
        for record in evidence_records
    )
    route_summary = (
        f"{escape(recommended_route.label)} - "
        f"{escape(' to '.join(recommended_route.countries))}"
        if recommended_route
        else "No route recommendation generated."
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>TradeTwin Compliance Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #172033; margin: 32px; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .badge {{ display: inline-block; padding: 6px 10px; border-radius: 4px;
      background: #ecfeff; color: #115e59; font-weight: 700; }}
    .disclaimer {{ background: #fff7ed; border: 1px solid #fed7aa;
      padding: 12px; margin: 18px 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; }}
    th {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <h1>TradeTwin Compliance Report</h1>
  <p class="badge">{escape(assessment.status)}</p>
  <p><strong>Shipment:</strong> {escape(shipment["shipment_reference"])}</p>
  <p><strong>Route:</strong> {escape(shipment["exporter_country"])}
    to {escape(shipment["importer_country"])} via {escape(shipment["transport_mode"])}</p>
  <div class="disclaimer">{escape(LEGAL_DISCLAIMER)}</div>

  <h2>Consignments</h2>
  <table>
    <thead>
      <tr>
        <th>Product</th><th>Origin</th><th>Destination</th><th>Quantity</th>
        <th>Declared value</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{consignment_rows}</tbody>
  </table>

  <h2>Compliance Rules</h2>
  <table>
    <thead>
      <tr>
        <th>Rule</th><th>Title</th><th>Jurisdiction</th><th>Procedure</th>
        <th>Version</th><th>Status</th><th>Missing documents</th>
      </tr>
    </thead>
    <tbody>{rule_rows}</tbody>
  </table>

  <h2>Corrective Action</h2>
  <p>{escape(assessment.result.recommended_action)}</p>

  <h2>Evidence Trace</h2>
  <ul>{evidence_items or "<li>No evidence records were returned.</li>"}</ul>

  <h2>Route Recommendation</h2>
  <p>{route_summary}</p>
</body>
</html>"""


def build_pdf_report(
    shipment: dict[str, Any],
    assessment: ComplianceAssessmentRead,
    evidence_records: list[dict[str, Any]],
    route_options: RouteOptimizationRead | None,
) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 48

    def draw_line(text: str, size: int = 10, bold: bool = False) -> None:
        nonlocal y
        if y < 56:
            pdf.showPage()
            y = height - 48
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(48, y, text[:110])
        y -= size + 8

    draw_line("TradeTwin Compliance Report", 16, True)
    draw_line(f"Shipment: {shipment['shipment_reference']}", 11, True)
    draw_line(f"Overall status: {assessment.status}", 11, True)
    draw_wrapped(pdf, LEGAL_DISCLAIMER, 48, y, width - 96)
    y -= wrapped_height(LEGAL_DISCLAIMER, width - 96) + 18

    draw_line("Consignments", 13, True)
    for item in shipment.get("consignments", []):
        draw_line(
            f"{item['product_name']} - {item['country_of_origin']} to "
            f"{item['destination_country']} - {item['customs_status']}"
        )

    draw_line("Rule Results", 13, True)
    for rule in assessment.result.applicable_rules:
        missing = ", ".join(rule.missing_documents) or "None"
        draw_line(f"{rule.rule_id} v{rule.version} - {rule.status} - missing: {missing}")

    draw_line("Corrective Action", 13, True)
    for line in wrap(assessment.result.recommended_action, width=92):
        draw_line(line)

    draw_line("Evidence Trace", 13, True)
    if evidence_records:
        for record in evidence_records:
            draw_line(f"{record.get('evidence_type')}: {record.get('explanation')}")
    else:
        draw_line("No evidence records were returned.")

    if route_options:
        recommended = next(
            (option for option in route_options.options if option.is_recommended),
            None,
        )
        if recommended:
            draw_line("Route Recommendation", 13, True)
            draw_line(f"{recommended.label} - {' to '.join(recommended.countries)}")

    pdf.save()
    return buffer.getvalue()


def draw_wrapped(pdf, text: str, x: int, y: float, max_width: float) -> None:
    del max_width
    pdf.setFont("Helvetica", 9)
    for line in wrap(text, width=92):
        pdf.drawString(x, y, line)
        y -= 13


def wrapped_height(text: str, max_width: float) -> int:
    del max_width
    return len(wrap(text, width=92)) * 13
