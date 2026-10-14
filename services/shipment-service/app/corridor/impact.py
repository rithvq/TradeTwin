"""Pure deterministic spatiotemporal impacts, with downstream bounded delay propagation."""

from datetime import datetime, timedelta

from app.freight.models import Dataset

from .geometry import match

ENGINE_VERSION = "CORRIDOR_IMPACT_1.0"
PRECISION = {"EXACT_EDGE": 4, "SOURCE_POLYGON": 3, "ADMIN_AREA": 2, "APPROXIMATE": 1, "UNKNOWN": 0}


def sections(dataset, route, departure, speed_cap_kph=None, uncertain_stops_seconds=0):
    edges = {e["edge_key"]: e for e in dataset["edges"]}
    result, cursor = [], datetime.fromisoformat(departure)
    for index, key in enumerate(route["ordered_edge_keys"]):
        edge = edges[key]
        reverse = edge["from_node_key"] != route["ordered_node_keys"][index]
        duration = (
            max(
                edge["estimated_driving_seconds"],
                (edge["distance_meters"] * 18 + speed_cap_kph * 5 - 1) // (speed_cap_kph * 5),
            )
            if speed_cap_kph
            else edge["estimated_driving_seconds"]
        )
        end = cursor + timedelta(seconds=duration)
        result.append(
            {
                "section_index": index,
                "edge_key": key,
                "dataset_revision_id": route["dataset_revision_id"],
                "state_codes": edge.get("ordered_state_sequence") or [],
                "district_codes": edge.get("district_codes", []),
                "direction": "REVERSE" if reverse else "FORWARD",
                "coordinates": edge.get("geometry", {}).get("coordinates")
                if edge.get("geometry", {}).get("type") == "LineString"
                else None,
                "entry_at": cursor.isoformat(),
                "exit_at": end.isoformat(),
                "latest_exit_at": (end + timedelta(seconds=uncertain_stops_seconds)).isoformat(),
                "history_basis": "PLANNED_NOT_OBSERVED",
            }
        )
        cursor = end
    return result


def temporal(section, event, shift):
    start, end = event["assessed_effective_from"], event["assessed_effective_until"]
    if not start or not end:
        return "POSSIBLE"
    entry = datetime.fromisoformat(section["entry_at"]) + timedelta(seconds=shift)
    exit_at = datetime.fromisoformat(section["exit_at"]) + timedelta(seconds=shift)
    latest = datetime.fromisoformat(section.get("latest_exit_at", section["exit_at"])) + timedelta(
        seconds=shift
    )
    if exit_at <= datetime.fromisoformat(start) < latest:
        return "POSSIBLE"
    return (
        "OVERLAP"
        if entry < datetime.fromisoformat(end) and datetime.fromisoformat(start) < exit_at
        else "NONE"
    )


def assess(route_sections, projection, vehicle_profile=None, cargo_profiles=None):
    items, seen, groups = [], set(), {}
    blocked = review = False
    unknown_delay = False
    shift = 0
    for section in route_sections:
        additions = {}
        for event in projection["events"]:
            geo = event["geography"]
            spatial = match(section, geo)
            if spatial == "NONE":
                continue
            if geo["direction"] not in {"BOTH", "UNKNOWN", section["direction"]}:
                continue
            if (
                event["vehicle_profile_codes"]
                and vehicle_profile
                and vehicle_profile not in event["vehicle_profile_codes"]
            ):
                continue
            if (
                event["cargo_profile_codes"]
                and cargo_profiles is not None
                and not set(cargo_profiles).intersection(event["cargo_profile_codes"])
            ):
                continue
            overlap = temporal(section, event, shift)
            unresolved_closure = event["event_kind"] in {
                "ROAD_CLOSURE",
                "TRAFFIC_RESTRICTION",
            } and event["state"] in {"STALE", "EXPIRED", "SUPERSEDED", "WITHDRAWN"}
            if overlap == "NONE" and not unresolved_closure:
                continue
            policies = [
                p
                for p in projection["policies"]
                if event["event_kind"] in p["event_kinds"]
                and event["source_kind"] in p["source_kinds"]
                and (
                    not p["state_codes"]
                    or set(section["state_codes"]).intersection(p["state_codes"])
                )
            ]
            for policy in policies or [None]:
                effect = policy["effect"] if policy else "REQUIRE_REVIEW"
                precision = (
                    policy and PRECISION[geo["precision"]] >= PRECISION[policy["minimum_precision"]]
                )
                aged = policy and (
                    datetime.fromisoformat(event["source_sent_at"])
                    + timedelta(seconds=policy["maximum_source_age_seconds"])
                    <= datetime.fromisoformat(projection["evaluated_as_of"])
                )
                scope_unknown = bool(
                    (event["vehicle_profile_codes"] and not vehicle_profile)
                    or (event["cargo_profile_codes"] and cargo_profiles is None)
                    or geo["direction"] == "UNKNOWN"
                    or (policy and policy["vehicle_profile_codes"] and not vehicle_profile)
                    or (policy and policy["cargo_profile_codes"] and cargo_profiles is None)
                )
                state_unknown = (
                    event["source_stale"]
                    or event["connection_status"] != "CONFIGURED"
                    or aged
                    or event["state"] not in {"ACTIVE", "FUTURE"}
                )
                uncertain = (
                    spatial == "POSSIBLE_MATCH"
                    or overlap != "OVERLAP"
                    or not precision
                    or scope_unknown
                    or state_unknown
                    or unresolved_closure
                )
                outcome = (
                    "NEEDS_REVIEW"
                    if uncertain or effect == "REQUIRE_REVIEW"
                    else "BLOCKED"
                    if effect == "EXCLUDE_EDGE"
                    else "ADVISORY"
                )
                if effect == "ADVISORY_ONLY" and not unresolved_closure:
                    outcome = "ADVISORY"
                blocked = blocked or outcome == "BLOCKED"
                review = review or outcome == "NEEDS_REVIEW"
                group = event["independence_group"] or event["incident_id"]
                delay = (
                    policy["maximum_delay_seconds"]
                    if policy and effect == "APPLY_DECLARED_DELAY_RANGE" and not uncertain
                    else None
                )
                if effect == "APPLY_DECLARED_DELAY_RANGE":
                    unknown_delay = unknown_delay or delay is None
                    if delay is not None:
                        additions[group] = max(additions.get(group, 0), delay)
                key = (event["id"], section["section_index"], policy["id"] if policy else None)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "event_revision_id": event["id"],
                        "event_hash": event["hash"],
                        "incident_id": event["incident_id"],
                        "policy_revision_id": policy["id"] if policy else None,
                        "policy_hash": policy["hash"] if policy else None,
                        "section_index": section["section_index"],
                        "edge_key": section["edge_key"],
                        "spatial_match": spatial,
                        "temporal_match": overlap,
                        "outcome": outcome,
                        "effect": effect,
                        "class": "APPLICATION_POLICY" if policy else "INFORMATIONAL",
                        "minimum_delay_seconds": policy["minimum_delay_seconds"]
                        if policy and delay is not None
                        else None,
                        "maximum_delay_seconds": delay,
                        "cost_minor": None,
                        "fixed_contract_repriced": False,
                        "source_reference": event["source_reference"],
                        "headline": event["headline"],
                        "event_state": event["state"],
                        "aggregation_group": group,
                        "limitations": event["limitations"]
                        + (
                            ["Expiry, withdrawal, supersession and outage do not prove reopening."]
                            if unresolved_closure
                            else []
                        ),
                    }
                )
        # A single incident or syndicated group is counted once, not once per edge/source.
        for group, amount in additions.items():
            old = groups.get(group, 0)
            groups[group] = max(old, amount)
            shift += max(0, amount - old)
    for policy in projection["policies"]:
        if (
            policy["missing_coverage_action"] == "REQUIRE_REVIEW"
            and projection["coverage"]["missing_scopes"]
        ):
            review = True
    return {
        "engine_version": ENGINE_VERSION,
        "outcome": "BLOCKED"
        if blocked
        else "NEEDS_REVIEW"
        if review
        else "ADVISORY"
        if items
        else "NO_APPLICABLE_EFFECT",
        "items": items,
        "maximum_additional_delay_seconds": None if unknown_delay or blocked or review else shift,
        "delay_aggregation": [
            {"group": k, "maximum_seconds": v} for k, v in sorted(groups.items())
        ],
        "contract_price_changed": False,
        "route_changed": False,
        "coverage": projection["coverage"],
        "limitations": [
            "Traversal is planned, not verified movement.",
            "No replacement carrier price is inferred from news or route distance.",
        ],
    }


def evaluate_plan(db, plan, projection):
    if not plan:
        return {"outcome": "NEEDS_REVIEW", "items": [], "limitations": ["No committed route plan."]}
    data = plan.route_plan_json
    route = data["route_snapshot"]
    dataset = db.get(Dataset, route["dataset_revision_id"])
    from app.compliance.clock import instant

    at = instant(db)
    value = {**projection, "evaluated_as_of": at.isoformat()}
    from app.freight.models import Profile

    profile = db.get(Profile, data["routing_vehicle_profile_revision_id"])
    departure = datetime.fromisoformat(data["planned_departure_at"])
    planned_seconds = int(
        (datetime.fromisoformat(data["estimated_arrival_at"]) - departure).total_seconds()
    )
    stops = max(0, planned_seconds - route["estimated_driving_seconds"])
    result = assess(
        sections(
            dataset.dataset_json,
            route,
            data["planned_departure_at"],
            profile.profile_json.get("speed_cap_kph"),
            stops,
        ),
        value,
    )
    delay = result["maximum_additional_delay_seconds"]
    result["nominal_arrival_at"] = data["estimated_arrival_at"]
    result["worst_case_arrival_at"] = (
        (
            datetime.fromisoformat(data["estimated_arrival_at"]) + timedelta(seconds=delay)
        ).isoformat()
        if delay is not None
        else None
    )
    from app.operations.models import Consignment

    cn = db.get(Consignment, plan.consignment_id)
    if cn.movement_status == "IN_TRANSIT":
        result["outcome"] = "NEEDS_REVIEW" if result["outcome"] != "BLOCKED" else "BLOCKED"
        result["limitations"].append(
            "Remaining-route recovery requires a reviewed fresh safe-stop anchor; "
            "historical traversal is not inferred."
        )
    return result
