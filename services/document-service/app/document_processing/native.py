"""Labelled native-text/table capture. Missing/ambiguous information is never invented."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

LABELS = {
    "document profile": "header.document_profile",
    "currency": "header.currency",
    "discount treatment": "totals.discount_treatment",
    "discount total": "totals.discount_total_minor",
    "cess amount": "totals.cess_total_minor",
    "state cess amount": "totals.state_cess_total_minor",
    "other charges": "totals.other_charges_minor",
    "round off": "totals.round_off_minor",
    "document number": "header.document_number",
    "invoice number": "header.document_number",
    "document date": "header.issue_date",
    "invoice date": "header.issue_date",
    "supplier gstin": "parties.supplier.gstin",
    "recipient gstin": "parties.recipient.gstin",
    "supplier name": "parties.supplier.legal_name",
    "recipient name": "parties.recipient.legal_name",
    "purchase order reference": "header.purchase_order_reference",
    "irn": "header.irn",
    "taxable goods amount": "totals.taxable_subtotal_minor",
    "taxable subtotal": "totals.taxable_subtotal_minor",
    "cgst amount": "totals.cgst_total_minor",
    "sgst amount": "totals.sgst_total_minor",
    "igst amount": "totals.igst_total_minor",
    "grand total": "totals.grand_total_minor",
    "gross weight kg": "packing_transport.gross_weight_kg",
    "net weight kg": "packing_transport.net_weight_kg",
    "package count": "packing_transport.package_count",
    "vehicle number": "packing_transport.vehicle_registration_number",
    "carrier name": "packing_transport.carrier_name",
    "lr gr number": "packing_transport.lr_gr_number",
    "eway bill number": "eway_bill.eway_bill_number",
    "delivery reference": "pod.delivery_reference",
    "payment reference": "payment_evidence.transaction_reference",
    "payment amount": "payment_evidence.amount_minor",
}


def empty():
    return {
        "schema_version": "PH3_CANONICAL_V1",
        "header": {},
        "parties": {},
        "lines": [],
        "totals": {},
        "packing_transport": {},
        "eway_bill": {},
        "pod": {},
        "payment_evidence": {},
    }


def value(path, raw):
    warnings, kind = [], "STRING"
    raw = raw.strip()
    if path.endswith("_minor"):
        kind = "MONEY_MINOR"
        match = re.fullmatch(r"(?:INR\s*)?([\d,]+(?:\.\d+)?)\s*(paise|INR|rupees)?", raw, re.I)
        if not match:
            return None, kind, ["Amount/unit is ambiguous."]
        amount = Decimal(match[1].replace(",", ""))
        if (match[2] or "").lower() != "paise":
            amount *= 100
        if amount != amount.to_integral_value():
            return None, kind, ["Fractional paise requires review."]
        return str(int(amount)), kind, warnings
    if path.endswith("issue_date"):
        kind = "DATE"
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError("Ambiguous date")
            return date.fromisoformat(raw).isoformat(), kind, warnings
        except ValueError:
            return None, kind, ["Date requires explicit human interpretation."]
    if path.endswith("gstin"):
        return raw.upper(), "IDENTIFIER", ["UPPERCASE_CONVERSION"] if raw != raw.upper() else []
    if path.endswith("package_count"):
        return (
            int(raw) if raw.isdigit() else None,
            "DECIMAL",
            [] if raw.isdigit() else ["Invalid count."],
        )
    if path.endswith(("quantity", "weight_kg")):
        try:
            return format(Decimal(raw), "f"), "DECIMAL", []
        except InvalidOperation:
            return None, "DECIMAL", ["Invalid decimal."]
    return raw, kind, warnings


def parse(lines, artifact_id):
    canonical, observations = empty(), []

    def observe(path, raw, source, row=None, override=None):
        normal, kind, warnings = value(path, raw) if override is None else (override, "STRING", [])
        observations.append(
            {
                "field_path": path,
                "row_key": row,
                "raw_text": raw,
                "normalised_value_json": normal,
                "value_type": kind,
                "extraction_method": source.get("method", "NATIVE_TEXT"),
                "provider_confidence": source.get("confidence"),
                "validation_status": "PARSED" if normal is not None else "AMBIGUOUS",
                "normalisation_warnings_json": warnings,
                "source_locator_json": {**source["locator"], "text_artifact_id": artifact_id},
            }
        )
        return normal

    for index, line in enumerate(lines):
        text = line["text"]
        matched = re.fullmatch(r"([^:]{1,70}):\s*(.+)", text)
        if matched:
            label = matched[1].strip().casefold()
            path = LABELS.get(label)
            if path:
                target = canonical
                parts = path.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = observe(path, matched[2], line)
        if re.match(r"^Line\s+\d+\s*\|", text, re.I):
            cells = [s.strip() for s in text.split("|")]
            if len(cells) < 7:
                continue
            row_key = f"page-{line['locator']['page_number']}-row-{index}"
            item = {"document_line_ref": str(uuid4())}
            for name, cell in zip(
                (
                    "line_number_printed",
                    "description",
                    "hsn_code",
                    "quantity",
                    "uqc",
                    "unit_price_minor",
                    "taxable_value_minor",
                ),
                cells,
                strict=False,
            ):
                if name == "line_number_printed":
                    cell = cell.removeprefix("Line ").strip()
                if name.endswith("_minor"):
                    cell = f"{cell} paise"
                item[name] = observe(f"lines.*.{name}", cell, line, row_key)
            canonical["lines"].append(item)
    return canonical, observations
