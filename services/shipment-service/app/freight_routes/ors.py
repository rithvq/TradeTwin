"""ORS supplies real HGV candidates; it does not supply live traffic or Indian legal clearance."""

import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

import httpx

from app.operations.access import fail
from app.trades.errors import TradeError
from app.trades.terms import digest

from .network import document


def closure_avoidance(snapshot, routes):
    """Only reviewed blocking polygons already approved for public disclosure leave the app."""
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    from app.corridor.impact import assess

    projection = snapshot["corridor"]
    if not projection["events"]:
        return None
    from app.compliance.clock import instant

    at = instant()
    departure = datetime.fromisoformat(snapshot["request"]["departure_at"])
    blocked = set()
    for route in routes:
        section = {
            "section_index": 0,
            "edge_key": route["id"],
            "dataset_revision_id": None,
            "state_codes": list(
                {s for e in projection["events"] for s in e["geography"]["state_codes"]}
            ),
            "district_codes": [],
            "direction": "FORWARD",
            "coordinates": route["geometry"]["coordinates"],
            "entry_at": departure.isoformat(),
            "exit_at": (departure + timedelta(seconds=route["driving_seconds"])).isoformat(),
        }
        effect = assess([section], {**projection, "evaluated_as_of": at.isoformat()})
        blocked.update(i["event_revision_id"] for i in effect["items"] if i["outcome"] == "BLOCKED")
    polygons = [
        shape(e["geography"]["geojson"])
        for e in projection["events"]
        if e["id"] in blocked
        and e.get("public_geometry")
        and e["geography"]["geometry_kind"] in {"POLYGON", "MULTIPOLYGON"}
    ]
    if not polygons:
        return None
    result = unary_union(polygons)
    return mapping(result) if result.geom_type in {"Polygon", "MultiPolygon"} else None


HOSTS = {"api.openrouteservice.org", "api.heigit.org"}
DEFAULT_URL = "https://api.heigit.org/openrouteservice/v2/directions/driving-hgv/geojson"


def endpoint():
    raw = os.getenv("ORS_DIRECTIONS_URL", DEFAULT_URL).rstrip("/")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in HOSTS
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        fail("ROUTE_SOURCE_NOT_APPROVED", "Configure an approved HTTPS ORS HGV endpoint.")
    expected = (
        "/openrouteservice/v2/directions/driving-hgv/"
        if parsed.hostname == "api.heigit.org"
        else "/v2/directions/driving-hgv/"
    )
    if parsed.path not in {expected + "json", expected + "geojson"}:
        fail("ROUTE_SOURCE_NOT_APPROVED", "Only the HGV directions endpoint is supported.")
    return raw.removesuffix("/json") + "/geojson" if raw.endswith("/json") else raw


def request_body(snapshot, preference="fastest", avoid_tolls=False, avoid_polygons=None):
    truck = snapshot["truck"]
    options = {
        "vehicle_type": "hgv",
        "avoid_borders": "all",
        "avoid_features": ["ferries", "fords", *(["tollways"] if avoid_tolls else [])],
        "profile_params": {
            "restrictions": {
                "height": float(truck["height_m"]),
                "width": float(truck["width_m"]),
                "length": float(truck["length_m"]),
                "axleload": float(Decimal(truck["axle_load_kg"]) / 1000),
                "weight": float(
                    (Decimal(truck["tare_kg"]) + Decimal(snapshot["cargo_weight_kg"])) / 1000
                ),
                "hazmat": snapshot["hazardous_declared"],
            }
        },
    }
    if avoid_polygons:
        options["avoid_polygons"] = avoid_polygons
    return {
        "coordinates": [snapshot["pickup"]["coordinates"], snapshot["drop"]["coordinates"]],
        "preference": preference,
        "instructions": True,
        "extra_info": ["waytype", "tollways", "roadaccessrestrictions", "countryinfo"],
        "options": options,
    }


def extra_metres(extras, key, accepted):
    summary = (extras.get(key) or {}).get("summary")
    if not isinstance(summary, list) or not summary:
        return None
    if any(
        not isinstance(i.get("distance"), int | float)
        or not math.isfinite(i["distance"])
        or i["distance"] < 0
        for i in summary
    ):
        return None
    return round(sum(i["distance"] for i in summary if i.get("value") in accepted))


def parse(response, variant, source_url):
    features = response.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= 6:
        fail("ROUTE_SOURCE_INVALID", "The HGV provider returned no usable road geometry.")
    output = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates", [])
        if geometry.get("type") != "LineString" or not 2 <= len(coords) <= 120000:
            fail("ROUTE_SOURCE_INVALID", "The HGV provider returned invalid road geometry.")
        if any(
            not isinstance(p, list)
            or len(p) < 2
            or not all(isinstance(n, int | float) and math.isfinite(n) for n in p[:2])
            or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90)
            for p in coords
        ):
            fail("ROUTE_SOURCE_INVALID", "The HGV provider returned invalid coordinates.")
        data = feature.get("properties") or {}
        summary = data.get("summary") or {}
        distance, duration = summary.get("distance"), summary.get("duration")
        if not all(
            isinstance(v, int | float) and math.isfinite(v) and v > 0 for v in (distance, duration)
        ):
            fail("ROUTE_SOURCE_INVALID", "The HGV provider returned invalid distance or duration.")
        extras = data.get("extras") or {}
        known = extra_metres(extras, "waytype", set(range(1, 11)))
        major = extra_metres(extras, "waytype", {1})
        tolls = extra_metres(extras, "tollways", {1})
        access_codes = sorted(
            {
                i["value"]
                for i in (extras.get("roadaccessrestrictions") or {}).get("summary", [])
                if isinstance(i.get("value"), int) and i["value"] > 0
            }
        )
        unknown_road = known is None or known < distance * 0.95
        names = list(
            dict.fromkeys(
                str(step.get("name", ""))[:160]
                for segment in data.get("segments", [])
                for step in segment.get("steps", [])
                if step.get("name") and step["name"] != "-"
            )
        )[:12]
        output.append(
            {
                "id": "road-" + digest([[round(p[0], 6), round(p[1], 6)] for p in coords])[:20],
                "label": variant,
                "geometry": {"type": "LineString", "coordinates": [p[:2] for p in coords]},
                "distance_m": round(distance),
                "driving_seconds": round(duration),
                "major_road_metres": major,
                "toll_road_metres": tolls,
                "road_exposure": None
                if unknown_road or major is None
                else round(100 * (1 - min(major, distance) / distance), 3),
                "road_names": names,
                "access_restriction_codes": access_codes,
                "provider_warning_codes": [
                    str(w.get("code", "PROVIDER_WARNING")) for w in data.get("warnings", [])
                ][:20],
                "provider": {
                    "name": "openrouteservice HGV / OpenStreetMap",
                    "url": source_url,
                    "attribution": "© openrouteservice / HeiGIT; © OpenStreetMap contributors",
                    "traffic": "MAP_ESTIMATE_NOT_LIVE_TRAFFIC",
                },
            }
        )
    return output


def fetch(snapshot, transport=None):
    if os.getenv("ALLOW_EXTERNAL_ROUTING", "false").lower() != "true" or not os.getenv(
        "ORS_API_KEY"
    ):
        fail(
            "PROVIDER_NOT_CONFIGURED",
            "Live truck routes require ORS_API_KEY and ALLOW_EXTERNAL_ROUTING=true.",
        )
    url, key = endpoint(), os.environ["ORS_API_KEY"]
    variants = [
        ("Fastest mapped truck route", "fastest", False),
        ("Shortest mapped truck route", "shortest", False),
        ("Truck route avoiding mapped tollways", "fastest", True),
    ]
    routes, failures = {}, []
    with httpx.Client(
        timeout=httpx.Timeout(25, connect=8), follow_redirects=False, transport=transport
    ) as client:

        def one(variant):
            label, preference, avoid, *polygon = variant
            response = document(
                client,
                "POST",
                url,
                hosts=HOSTS,
                headers={"Authorization": key},
                payload=request_body(snapshot, preference, avoid, polygon[0] if polygon else None),
            )
            return parse(response, label, url)

        with ThreadPoolExecutor(max_workers=3) as pool:
            for variant, future in zip(
                variants, [pool.submit(one, v) for v in variants], strict=True
            ):
                try:
                    for route in future.result():
                        if route["id"] in routes:
                            routes[route["id"]].setdefault("also_returned_for", []).append(
                                variant[0]
                            )
                        else:
                            routes[route["id"]] = route
                except TradeError as error:
                    failures.append({"variant": variant[0], "code": error.code})
        polygons = closure_avoidance(snapshot, list(routes.values()))
        if polygons:
            variant = ("Detour around reviewed public closures", "fastest", False, polygons)
            try:
                for route in one(variant):
                    routes.setdefault(route["id"], route)
            except TradeError as error:
                failures.append({"variant": variant[0], "code": error.code})
    if not routes:
        fail(
            failures[0]["code"] if failures else "PROVIDER_UNAVAILABLE",
            "No live HGV alternative could be confirmed. No synthetic fallback was used.",
            status=503,
        )
    return list(routes.values()), failures
