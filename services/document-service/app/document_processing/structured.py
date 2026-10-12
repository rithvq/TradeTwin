import base64
import json
import re
from decimal import Decimal
from uuid import uuid4


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def lossless_json(content):
    def nonfinite(value):
        raise ValueError("Non-finite JSON number")

    return json.loads(
        content,
        parse_int=str,
        parse_float=str,
        parse_constant=nonfinite,
        object_pairs_hook=unique_object,
    )


def compact_payload(token):
    parts = token.split(".")
    if len(parts) != 3 or any(not p for p in parts):
        raise ValueError("Unsupported compact signature")
    return lossless_json(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))


def parse(content, attachment_id):
    data = lossless_json(content)
    if not isinstance(data, dict):
        raise ValueError("Structured document must be an object")
    canonical = {
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
    observations = []
    tokens = {
        key: data[key]
        for key in ("SignedInvoice", "SignedQRCode")
        if isinstance(data.get(key), str)
    }
    pointer_prefix = ""
    if tokens:
        chosen = "SignedInvoice" if "SignedInvoice" in tokens else "SignedQRCode"
        data = compact_payload(tokens[chosen])
        if not isinstance(data, dict):
            raise ValueError("Signed business payload must be an object")
        if isinstance(data.get("data"), str):
            data = lossless_json(data["data"])
        pointer_prefix = f"/{chosen}/@decoded"

    def add(path, raw, pointer, row_key=None, money=False):
        if raw is None:
            return
        value = str(raw) if not isinstance(raw, dict | list | bool) else raw
        if money:
            value = format(Decimal(str(raw)) * 100, "f")
            if Decimal(value) != Decimal(value).to_integral_value():
                raise ValueError("Money has fractional paise")
            value = str(int(Decimal(value)))
        observations.append(
            {
                "field_path": path,
                "row_key": row_key,
                "raw_text": str(raw),
                "normalised_value_json": value,
                "value_type": "MONEY_MINOR" if money else "STRING",
                "extraction_method": "STRUCTURED_JSON",
                "provider_confidence": None,
                "validation_status": "PARSED",
                "normalisation_warnings_json": [
                    f"Decoded field path: {pointer}; signature not checked."
                ]
                if pointer_prefix
                else [],
                "source_locator_json": {
                    "source_attachment_id": attachment_id,
                    "json_pointer": pointer_prefix.split("/@decoded")[0]
                    if pointer_prefix
                    else pointer,
                },
            }
        )
        return value

    if data.get("schema_version") == "PH3_CANONICAL_V1":
        allowed = set(canonical)
        if set(data) - allowed:
            raise ValueError("Unsupported structured document fields")
        canonical.update(data)
        for line in canonical.get("lines", []):
            line["document_line_ref"] = str(uuid4())

        def walk(value, prefix="", pointer="", row=None):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key not in {"schema_version", "document_line_ref"}:
                        walk(item, f"{prefix}.{key}" if prefix else key, f"{pointer}/{key}", row)
            elif isinstance(value, list) and prefix == "lines":
                for index, line in enumerate(value):
                    walk(line, "lines.*", f"/lines/{index}", str(index))
            elif value is not None:
                add(prefix, value, pointer, row)

        walk(canonical)
    elif isinstance(data.get("DocDtls"), dict) and isinstance(data.get("ItemList"), list):
        header = canonical["header"]
        for key, name in {"No": "document_number", "Dt": "issue_date"}.items():
            raw = data["DocDtls"].get(key)
            value = add(f"header.{name}", raw, f"/DocDtls/{key}")
            if name == "issue_date" and value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                observations[-1]["normalised_value_json"] = None
                observations[-1]["validation_status"] = "AMBIGUOUS"
                observations[-1]["normalisation_warnings_json"] = [
                    "Date requires explicit human interpretation."
                ]
                value = None
            header[name] = value
        header["document_profile"] = "SUPPORTED_STRUCTURED_PROFILE"
        header["currency"] = "INR"
        for source, target in {
            "SellerDtls": "supplier",
            "BuyerDtls": "recipient",
            "DispDtls": "dispatch_from",
            "ShipDtls": "ship_to",
        }.items():
            party = {}
            for key, name in {
                "Gstin": "gstin",
                "LglNm": "legal_name",
                "TrdNm": "trade_name",
            }.items():
                raw = (data.get(source) or {}).get(key)
                value = add(f"parties.{target}.{name}", raw, f"/{source}/{key}")
                if name == "gstin" and value:
                    value = value.upper()
                    observations[-1]["normalised_value_json"] = value
                    observations[-1]["normalisation_warnings_json"] = (
                        ["UPPERCASE_CONVERSION"] if value != raw else []
                    )
                party[name] = value
            canonical["parties"][target] = party
        for index, source in enumerate(data["ItemList"]):
            row = str(index)
            line = {"document_line_ref": str(uuid4())}
            mapping = {
                "SlNo": "line_number_printed",
                "PrdDesc": "description",
                "HsnCd": "hsn_code",
                "Qty": "quantity",
                "Unit": "uqc",
                "UnitPrice": "unit_price_minor",
                "AssAmt": "taxable_value_minor",
                "Discount": "line_discount_minor",
                "CgstAmt": "cgst_amount_minor",
                "SgstAmt": "sgst_amount_minor",
                "IgstAmt": "igst_amount_minor",
                "TotItemVal": "line_total_minor",
            }
            for key, name in mapping.items():
                raw = source.get(key)
                line[name] = add(
                    f"lines.*.{name}", raw, f"/ItemList/{index}/{key}", row, name.endswith("_minor")
                )
            canonical["lines"].append(line)
        for key, name in {
            "AssVal": "taxable_subtotal_minor",
            "CgstVal": "cgst_total_minor",
            "SgstVal": "sgst_total_minor",
            "IgstVal": "igst_total_minor",
            "TotInvVal": "grand_total_minor",
            "RndOffAmt": "round_off_minor",
        }.items():
            canonical["totals"][name] = add(
                f"totals.{name}",
                (data.get("ValDtls") or {}).get(key),
                f"/ValDtls/{key}",
                money=True,
            )
    else:
        # A compact signed QR may cover only identifiers and totals, not full invoice lines.
        qr_fields = {
            "SellerGstin": "parties.supplier.gstin",
            "BuyerGstin": "parties.recipient.gstin",
            "DocNo": "header.document_number",
            "DocDt": "header.issue_date",
            "Irn": "header.irn",
        }
        if not tokens or not set(data) & set(qr_fields):
            raise ValueError("Unsupported structured document profile")
        for key, path in qr_fields.items():
            if data.get(key) is not None:
                parts = path.split(".")
                target = canonical
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                target[parts[-1]] = add(path, data[key], f"/{key}")
    return canonical, observations, tokens
