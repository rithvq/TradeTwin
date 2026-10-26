"""Route-time model forecasts are observations for comparison, never road-closure authority."""

import math
import os

from shapely.geometry import LineString

from app.trades.errors import TradeError

from .network import document

PUBLIC = "https://api.open-meteo.com/v1/forecast"
COMMERCIAL = "https://customer-api.open-meteo.com/v1/forecast"


def samples(routes, departure, stops=0):
    points = []
    for route in routes:
        line = LineString(route["geometry"]["coordinates"])
        for i in range(7):
            point = line.interpolate(i / 6, normalized=True)
            points.append(
                {
                    "route_id": route["id"],
                    "lon": round(point.x, 4),
                    "lat": round(point.y, 4),
                    "at": int(departure.timestamp() + (route["driving_seconds"] + stops) * i / 6),
                }
            )
    return points


def fetch(client, routes, departure, enabled, stops=0):
    if not enabled:
        return {
            r["id"]: {"status": "NOT_REQUESTED", "exposure": None, "samples": []} for r in routes
        }
    plan = os.getenv("FREIGHT_WEATHER_PLAN", "NON_COMMERCIAL").upper()
    key = os.getenv("OPEN_METEO_API_KEY")
    if plan not in {"NON_COMMERCIAL", "COMMERCIAL"} or (plan == "COMMERCIAL" and not key):
        return {
            r["id"]: {"status": "NOT_CONFIGURED", "exposure": None, "samples": []} for r in routes
        }
    points = samples(routes, departure, stops)
    endpoint = COMMERCIAL if plan == "COMMERCIAL" else PUBLIC
    params = {
        "latitude": ",".join(str(p["lat"]) for p in points),
        "longitude": ",".join(str(p["lon"]) for p in points),
        "hourly": "precipitation,wind_gusts_10m,visibility",
        "forecast_days": 16,
        "timezone": "UTC",
        "timeformat": "unixtime",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    if plan == "COMMERCIAL":
        params["apikey"] = key
    try:
        payload = document(
            client,
            "GET",
            endpoint,
            hosts={"api.open-meteo.com", "customer-api.open-meteo.com"},
            params=params,
            limit=8_000_000,
        )
        rows = payload if isinstance(payload, list) else [payload]
        if len(rows) != len(points):
            raise ValueError("Incomplete weather response")
        results = {
            r["id"]: {
                "status": "CURRENT_FORECAST",
                "exposure": None,
                "samples": [],
                "source_url": endpoint,
                "attribution": "Open-Meteo / contributing weather models; CC BY 4.0",
                "method": "Seven sampled positions with driving and declared stops "
                "spread approximately along the route; not continuous road monitoring.",
            }
            for r in routes
        }
        for point, row in zip(points, rows, strict=True):
            hourly = row.get("hourly", {})
            times = hourly.get("time", [])
            index = next((i for i, at in enumerate(times) if at <= point["at"] < at + 3600), None)
            values = {
                name: hourly.get(name, [])[index]
                if index is not None and index < len(hourly.get(name, []))
                else None
                for name in ("precipitation", "wind_gusts_10m", "visibility")
            }
            valid = all(
                isinstance(v, int | float) and math.isfinite(v) and v >= 0 for v in values.values()
            )
            target = results[point["route_id"]]
            target["samples"].append(
                {
                    "latitude": point["lat"],
                    "longitude": point["lon"],
                    "at_unix": point["at"],
                    **values,
                }
            )
            if not valid:
                target["status"] = "INCOMPLETE_OR_OUTSIDE_FORECAST_WINDOW"
        for result in results.values():
            if result["status"] == "CURRENT_FORECAST":
                result["exposure"] = round(
                    max(
                        max(
                            min(100, s["precipitation"] * 8),
                            min(100, max(0, s["wind_gusts_10m"] - 30) * 2),
                            min(100, max(0, 2000 - s["visibility"]) / 20),
                        )
                        for s in result["samples"]
                    ),
                    3,
                )
                result["index_basis"] = (
                    "APPLICATION_COMPARISON_HEURISTIC_NOT_OFFICIAL_WARNING_THRESHOLD"
                )
        return results
    except (TradeError, ValueError, KeyError, TypeError, IndexError):
        return {r["id"]: {"status": "UNAVAILABLE", "exposure": None, "samples": []} for r in routes}
