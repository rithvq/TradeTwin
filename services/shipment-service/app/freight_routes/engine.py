"""Combine live road candidates with captured state, permit, corridor and history evidence."""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import httpx

from app.corridor.impact import assess, sections
from app.trades.errors import TradeError
from app.trades.reference import STATES

from . import geography, history, ors, retained, rule_sources, weather
from .ranking import ENGINE_VERSION, compare


def scoped_projection(projection, states, at):
    coverage = projection["coverage"]
    missing = [s for s in coverage["missing_scopes"] if s["state_code"] in states]
    checked = [s for s in coverage["checked_sources"] if set(s["state_codes"]) & states]
    return {
        **projection,
        "evaluated_as_of": at.isoformat(),
        "coverage": {
            **coverage,
            "missing_scopes": missing,
            "checked_sources": checked,
            "status": "PARTIAL"
            if missing or any(s["status"] != "CURRENT" for s in checked)
            else "CURRENT"
            if checked
            else "NOT_CONFIGURED",
        },
    }


def route_sections(route, departure, stops):
    if route.get("sections"):
        captured = route.pop("sections")
        return sections(
            captured["dataset"],
            captured["route"],
            departure.isoformat(),
            uncertain_stops_seconds=stops,
        )
    return [
        {
            "section_index": 0,
            "edge_key": route["id"],
            "dataset_revision_id": None,
            "state_codes": [s for s in route["corridor"]["state_sequence"] if s],
            "district_codes": [],
            "direction": "FORWARD",
            "coordinates": route["geometry"]["coordinates"],
            "entry_at": departure.isoformat(),
            "exit_at": (departure + timedelta(seconds=route["driving_seconds"])).isoformat(),
            "latest_exit_at": (
                departure + timedelta(seconds=route["driving_seconds"] + stops)
            ).isoformat(),
        }
    ]


def evaluate(snapshot, *, transport=None, checked_at=None):
    from app.compliance.clock import instant

    at = checked_at or instant()
    request = snapshot["request"]
    departure = datetime.fromisoformat(request["departure_at"])
    live = request["source_mode"] == "LIVE"
    routes, failures = ors.fetch(snapshot, transport) if live else retained.alternatives(snapshot)
    sources = []
    with httpx.Client(
        timeout=httpx.Timeout(20, connect=8), follow_redirects=False, transport=transport
    ) as client:
        boundaries = None
        if live:
            try:
                boundaries = geography.load(client)
            except (TradeError, OSError, ValueError, KeyError):
                pass
        for route in routes:
            if live:
                route["geometry_kind"] = "ROAD_GEOMETRY"
                route["corridor"] = (
                    geography.corridor(route["geometry"]["coordinates"], boundaries)
                    if boundaries
                    else {
                        "state_sequence": [],
                        "state_names": [],
                        "mapping_status": "UNAVAILABLE",
                        "state_outlines": [],
                        "boundaries": {
                            "name": "State boundary reference unavailable",
                            "status": "UNAVAILABLE",
                        },
                    }
                )
        forecasts = weather.fetch(
            client,
            routes,
            departure,
            request["include_weather"] and live,
            stops=request["planned_stop_seconds"],
        )
        sources = rule_sources.check(client, snapshot["policy"]["sources"], live)
    for route in routes:
        reasons, excluded = [], False
        corridor = route["corridor"]
        sequence = corridor["state_sequence"]
        if not sequence or None in sequence:
            reasons.append("STATE_CORRIDOR_NOT_FULLY_MAPPED")
        elif (
            sequence[0] != snapshot["pickup"]["state_code"]
            or sequence[-1] != snapshot["drop"]["state_code"]
        ):
            reasons.append("STATE_PIN_BOUNDARY_CONFLICT")
            excluded = True
        if live:
            reasons.append("MAP_RESTRICTIONS_NOT_INDEPENDENT_LEGAL_VERIFICATION")
        if route.get("retained_assessment") == "FAIL":
            excluded = True
            reasons.append("TRUCK_RESTRICTION_FAILED")
        elif route.get("retained_assessment") == "UNKNOWN":
            reasons.append("TRUCK_RESTRICTION_COVERAGE_INCOMPLETE")
        if route["provider_warning_codes"]:
            reasons.append("PROVIDER_RESTRICTION_WARNING")
        if route.get("access_restriction_codes"):
            reasons.append("MAPPED_ROAD_ACCESS_CONDITIONS_REQUIRE_REVIEW")
        if any(code & 1 for code in route.get("access_restriction_codes", [])):
            excluded = True
            reasons.append("MAPPED_NO_ACCESS_RESTRICTION")
        known_states = [s for s in sequence if s]
        permitted = snapshot["permit_coverage"]["covered_states"]
        if not permitted:
            reasons.append("VEHICLE_PERMIT_COVERAGE_UNCONFIRMED")
        elif known_states and not set(known_states).issubset(permitted):
            reasons.append("CURRENT_PERMIT_DOES_NOT_COVER_CORRIDOR")
            excluded = True
        supported = sequence in snapshot["policy"]["supported_corridors"]
        if not supported:
            reasons.append("PUBLISHED_COMPLIANCE_SCOPE_REQUIRES_REVIEW")
        if any(s["status"] != "CAPTURED_BYTES_UNCHANGED" for s in sources) and live:
            reasons.append("OFFICIAL_RULE_SOURCE_CURRENCY_REQUIRES_REVIEW")
        projection = scoped_projection(snapshot["corridor"], set(known_states), at)
        impact = assess(
            route_sections(route, departure, request["planned_stop_seconds"]),
            projection,
            cargo_profiles=["HAZARDOUS"] if snapshot["hazardous_declared"] else None,
        )
        excluded = excluded or impact["outcome"] == "BLOCKED"
        if impact["outcome"] in {"BLOCKED", "NEEDS_REVIEW"}:
            reasons.append("REVIEWED_CORRIDOR_" + impact["outcome"])
        if projection["coverage"]["status"] != "CURRENT":
            reasons.append("LIVE_INCIDENT_COVERAGE_INCOMPLETE")
        extra = impact["maximum_additional_delay_seconds"]
        nominal = route["driving_seconds"] + request["planned_stop_seconds"]
        duration = nominal + extra if extra is not None else None
        if extra is None:
            reasons.append("ADDITIONAL_DELAY_AND_ARRIVAL_UNCERTAIN")
        forecast = forecasts[route["id"]]
        observed = history.summary(snapshot["history"], sequence)
        exposure = route["road_exposure"]
        if request["include_weather"]:
            exposure = (
                max(exposure, forecast["exposure"])
                if exposure is not None and forecast["exposure"] is not None
                else None
            )
        if exposure is None:
            reasons.append("ROAD_OR_WEATHER_EXPOSURE_UNKNOWN")
        end = snapshot["permit_coverage"].get("valid_until")
        arrival = departure + timedelta(seconds=duration if duration is not None else nominal)
        if end and arrival >= datetime.fromisoformat(end):
            excluded = True
            reasons.append("PERMIT_EXPIRES_BEFORE_ESTIMATED_ARRIVAL")
        if snapshot["hazardous_declared"]:
            reasons.append("HAZARDOUS_GOODS_REQUIRE_SPECIALIST_REVIEW")
        route.update(
            feasibility="EXCLUDED" if excluded else "CONDITIONAL" if reasons else "ASSESSED",
            reason_codes=sorted(set(reasons)),
            weather=forecast,
            history=observed,
            incident_impacts=impact["items"],
            incident_coverage=impact["coverage"],
            nominal_arrival_at=(departure + timedelta(seconds=nominal)).isoformat(),
            estimated_arrival_at=arrival.isoformat() if duration is not None else None,
            historic_adjusted_arrival_at=(
                arrival + timedelta(seconds=observed["ranking_extra_seconds"])
            ).isoformat()
            if duration is not None and observed["ranking_extra_seconds"] is not None
            else None,
            metrics={
                "distance": route["distance_m"],
                # Mapped drive and declared stops are observed independently of unknown delays.
                # Uncertain operational delay is never added as a fabricated zero-delay ETA.
                "duration": nominal,
                "road_weather_exposure": exposure,
                "state_transit_history": observed["ranking_extra_seconds"],
                "toll_exposure": route["toll_road_metres"],
            },
            state_requirements=[
                {
                    "position": i + 1,
                    "state_code": code,
                    "name": STATES.get(code, "Unresolved"),
                    "permit_status": "COVERED_BY_REVIEWED_DECLARATION"
                    if code in permitted
                    else "NEEDS_EVIDENCE",
                    "published_corridor_scope": "SUPPORTED_PROFILE"
                    if supported
                    else "REQUIRES_REVIEW",
                }
                for i, code in enumerate(sequence)
            ],
        )
        if request.get("fuel_price_per_litre_minor"):
            litres = Decimal(route["distance_m"]) / 1000 / Decimal(request["fuel_km_per_litre"])
            route["fuel_estimate_minor"] = str(
                (litres * request["fuel_price_per_litre_minor"]).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
        else:
            route["fuel_estimate_minor"] = None
    return {
        "engine_version": ENGINE_VERSION,
        "checked_at": at.isoformat(),
        "source_mode": request["source_mode"],
        "execution_mode": snapshot["execution_mode"],
        "candidates": routes,
        "comparison": compare(routes, request["weights"]),
        "provider_failures": failures,
        "policy_sources": sources,
        "policy_packs": snapshot["policy"]["packs"],
        "weights": request["weights"],
        "departure_at": request["departure_at"],
        "limitations": [
            "Domestic state transit requirements are not international customs duties.",
            "Travel-time ranking uses mapped driving plus declared stops. "
            "Operational delay and arrival certainty are shown separately.",
            "Unknown safety, security, traffic and policy coverage "
            "is not treated as clear or zero risk.",
            "Fuel costs are declared-input estimates; toll-road exposure "
            "is not a toll price or carrier quote.",
            "No commercial commitment, accepted price, route plan "
            "or dispatch authorization is changed.",
        ],
    }
