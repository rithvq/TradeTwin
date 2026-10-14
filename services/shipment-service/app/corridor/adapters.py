"""Bounded, side-effect-free adapters. Parsing never publishes an operational event."""

import json
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from defusedxml import ElementTree

MAX_BYTES = 5 * 1024 * 1024
CONTRACTS = {
    "IMD_NOWCAST_V1": {
        "endpoint": "https://api.imd.gov.in/api/v1/districtnowcast",
        "colors": {"1": "GREEN", "2": "YELLOW", "3": "ORANGE", "4": "RED"},
    },
    "IMD_DISTRICT_WARNING_V1": {
        "endpoint": "https://api.imd.gov.in/api/v1/districtwarning",
        "colors": {"1": "RED", "2": "ORANGE", "3": "YELLOW", "4": "GREEN"},
    },
}


def bounded_tree(value, deadline, depth=0):
    if depth > 64 or time.monotonic() > deadline:
        raise ValueError("Source exceeds nesting or parse-time limit")
    if isinstance(value, dict):
        for child in value.values():
            bounded_tree(child, deadline, depth + 1)
    elif isinstance(value, list):
        for child in value:
            bounded_tree(child, deadline, depth + 1)


def weather(content, contract_version, mapping):
    if len(content) > MAX_BYTES or contract_version not in CONTRACTS:
        raise ValueError("Oversized source or unknown endpoint contract")
    deadline = time.monotonic() + 10
    rows = json.loads(content)
    bounded_tree(rows, deadline)
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Weather batch must contain at most 1000 records")
    output = []
    for row in rows:
        administrative_id = str(row.get("Obj_id", row.get("District_ID", "")))
        district = mapping.get(administrative_id)
        colors = CONTRACTS[contract_version]["colors"]
        if contract_version == "IMD_NOWCAST_V1":
            local = datetime.strptime(
                row["Date"] + " " + str(row["toi"]).zfill(4), "%Y-%m-%d %H%M"
            ).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            end = datetime.strptime(
                row["Date"] + " " + str(row["Vupto"]).zfill(4), "%Y-%m-%d %H%M"
            ).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            if end <= local:
                end += timedelta(days=1)
            color = colors.get(str(row.get("color")))
            output.append(
                {
                    "provider_item_key": f"{administrative_id}:{local.isoformat()}",
                    "source_record": row,
                    "district_code": district,
                    "severity": color,
                    "issued_at": local.astimezone(UTC).isoformat(),
                    "effective_until": end.astimezone(UTC).isoformat(),
                    "time_interpretation": (
                        "IMD local HHmm, Asia/Kolkata; midnight rollover preserved"
                    ),
                    "needs_review": not district or color is None,
                }
            )
        else:
            # Warning days are source day windows, not arbitrary TTL from retrieval time.
            for day in range(1, 6):
                color = colors.get(str(row.get(f"Day{day}_Color")))
                output.append(
                    {
                        "provider_item_key": f"{administrative_id}:{row['Date']}:day{day}",
                        "source_record": row,
                        "district_code": district,
                        "severity": color,
                        "warning_day": day,
                        "time_interpretation": (
                            "Source Date and UTC retained; reviewed daily window required"
                        ),
                        "needs_review": True,
                    }
                )
    return output


def cap(content):
    if len(content) > MAX_BYTES:
        raise ValueError("CAP exceeds 5 MiB")
    deadline = time.monotonic() + 10
    root = ElementTree.fromstring(
        content, forbid_dtd=True, forbid_entities=True, forbid_external=True
    )
    if root.tag != "{urn:oasis:names:tc:emergency:cap:1.2}alert":
        raise ValueError("Expected CAP 1.2 alert namespace")
    ns = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

    def visit(element, depth=0):
        if (
            depth > 64
            or time.monotonic() > deadline
            or element.tag.startswith("{http://www.w3.org/2001/XInclude}")
        ):
            raise ValueError("Unsafe or excessively nested CAP")
        for child in element:
            visit(child, depth + 1)

    visit(root)

    def text(element, name):
        return element.findtext("cap:" + name, namespaces=ns)

    identity = {
        name: text(root, name)
        for name in ("sender", "identifier", "sent", "status", "msgType", "scope", "references")
    }
    if not all(identity[k] for k in ("sender", "identifier", "sent", "status", "msgType", "scope")):
        raise ValueError("CAP identity fields are incomplete")
    if identity["status"] not in {"Actual", "Exercise", "System", "Test", "Draft"} or identity[
        "msgType"
    ] not in {"Alert", "Update", "Cancel", "Ack", "Error"}:
        raise ValueError("Unknown CAP status or message type")
    sent = datetime.fromisoformat(identity["sent"])
    if sent.tzinfo is None:
        raise ValueError("CAP sent requires a timezone")
    infos = []
    for info in root.findall("cap:info", ns):
        item = {
            k: text(info, k)
            for k in (
                "language",
                "event",
                "severity",
                "urgency",
                "certainty",
                "effective",
                "onset",
                "expires",
                "headline",
                "description",
                "instruction",
            )
        }
        polygons = []
        for polygon in info.findall("cap:area/cap:polygon", ns):
            pairs = (polygon.text or "").split()
            if len(pairs) > 10000:
                raise ValueError("CAP polygon exceeds vertex limit")
            ring = [[float(lon), float(lat)] for lat, lon in (pair.split(",") for pair in pairs)]
            from .geometry import validate_geometry

            geojson = {"type": "Polygon", "coordinates": [ring]}
            validate_geometry(geojson)
            polygons.append(geojson)
        item["polygons"] = polygons
        infos.append(item)
    return {
        **identity,
        "infos": infos,
        "references": (identity["references"] or "").split(),
        "operationally_publishable": identity["status"] == "Actual"
        and identity["msgType"] in {"Alert", "Update"},
        "raw_timezone_preserved": True,
    }
