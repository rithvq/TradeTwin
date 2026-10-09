import re
from datetime import date, datetime
from io import BytesIO
from typing import Any

import pdfplumber
from pypdf import PdfReader

FIELD_PATTERNS = {
    "consignor_gstin": [r"consignor\s+gstin\s*[:\-]\s*(?P<value>[A-Z0-9]{15})"],
    "consignee_gstin": [r"consignee\s+gstin\s*[:\-]\s*(?P<value>[A-Z0-9]{15})"],
    "origin_state": [r"origin\s+state\s*[:\-]\s*(?P<value>[^\r\n]+)"],
    "destination_state": [r"destination\s+state\s*[:\-]\s*(?P<value>[^\r\n]+)"],
    "vehicle_number": [r"vehicle\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[A-Z0-9 -]+)"],
    "eway_bill_number": [r"e[ -]?way\s+bill\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[0-9]{12})"],
    "product_name": [
        r"product(?:\s+name)?\s*[:\-]\s*(?P<value>.+)",
        r"goods\s*[:\-]\s*(?P<value>.+)",
    ],
    "quantity": [r"quantity\s*[:\-]\s*(?P<value>[0-9][0-9,]*(?:\.\d+)?)"],
    "declared_value": [
        r"declared\s+value\s*[:\-]\s*(?P<value>(?:[A-Z]{3}\s*)?[0-9][0-9,]*(?:\.\d+)?)",
        r"(?:invoice\s+)?amount\s*[:\-]\s*(?P<value>(?:[A-Z]{3}\s*)?[0-9][0-9,]*(?:\.\d+)?)",
    ],
    "country_of_origin": [
        r"country\s+of\s+origin\s*[:\-]\s*(?P<value>.+)",
        r"origin\s+country\s*[:\-]\s*(?P<value>.+)",
    ],
    "hs_code": [
        r"hsn\s*(?:code)?\s*[:\-]\s*(?P<value>[0-9.]+)",
        r"hs\s+code\s*[:\-]\s*(?P<value>[0-9.]+)",
        r"proposed\s+hs\s+code\s*[:\-]\s*(?P<value>[0-9.]+)",
    ],
    "document_number": [
        r"e[ -]?way\s+bill\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[0-9]{12})",
        r"challan\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[A-Z0-9\-/]+)",
        r"document\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[A-Z0-9\-\/]+)",
        r"certificate\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[A-Z0-9\-\/]+)",
        r"invoice\s+(?:number|no\.?)\s*[:\-]\s*(?P<value>[A-Z0-9\-\/]+)",
    ],
    "document_date": [
        r"document\s+date\s*[:\-]\s*(?P<value>[A-Za-z0-9,\-\/ ]+)",
        r"certificate\s+date\s*[:\-]\s*(?P<value>[A-Za-z0-9,\-\/ ]+)",
        r"invoice\s+date\s*[:\-]\s*(?P<value>[A-Za-z0-9,\-\/ ]+)",
    ],
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d %B %Y",
    "%B %d, %Y",
)


def extract_document_fields(
    content: bytes,
    filename: str,
    content_type: str,
) -> tuple[str, dict[str, Any]]:
    text = extract_text(content, filename, content_type)
    fields: dict[str, Any] = {}

    for field_name, patterns in FIELD_PATTERNS.items():
        value = first_match(text, patterns)
        if value is None:
            continue
        if field_name == "document_date":
            parsed_date = parse_date(value)
            fields[field_name] = parsed_date.isoformat() if parsed_date else clean_value(value)
            continue
        if field_name == "quantity":
            fields[field_name] = clean_value(value).replace(",", "")
            continue
        fields[field_name] = clean_value(value)

    return text, fields


def extract_text(content: bytes, filename: str, content_type: str) -> str:
    is_pdf = filename.lower().endswith(".pdf") or content_type == "application/pdf"
    if not is_pdf:
        return content.decode("utf-8", errors="ignore")

    pdf_stream = BytesIO(content)
    try:
        with pdfplumber.open(pdf_stream) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception:
        pdf_stream.seek(0)
        reader = PdfReader(pdf_stream)
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group("value")
    return None


def clean_value(value: str) -> str:
    return value.strip().strip(".;,")


def parse_date(value: str) -> date | None:
    cleaned = clean_value(value)
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    return None
