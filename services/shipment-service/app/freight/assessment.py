"""Hypothetical planning checks reuse Phase 4 predicates but cannot mint a release."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal

from app.compliance.expression import evaluate

from .calculator import LIMITATIONS, cost, timing
from .routing import path_snapshot

POST_SELECTION = [
    "CARRIER_ASSIGNMENT_ACCEPTANCE",
    "ACTUAL_VEHICLE_EVIDENCE_BINDINGS",
    "EWB_VEHICLE_UPDATE_OR_REPLACEMENT",
    "FRESH_AUTHORITY_OBSERVATIONS",
    "COMPLIANCE_FACT_REVIEW",
    "ACTUAL_LOADING_MANIFEST",
    "FRESH_PHASE4_EVALUATION",
    "INDEPENDENT_RELEASE_REVIEW",
    "DISPATCH_PACKET",
    "ASSIGNED_DRIVER_ACK",
    "ACTION_BOUND_AUTHORISATION",
]


def requirement(code, value, explanation, observed=None, expected=None, refs=None):
    return {
        "requirement_code": code,
        "category": "HARD_PLANNING_CONSTRAINT",
        "class": "APPLICATION_POLICY",
        "outcome": "PASS" if value is True else "FAIL" if value is False else "UNKNOWN",
        "explanation": explanation,
        "observed": observed,
        "expected": expected,
        "source_refs": refs or [],
    }


def assess(snapshot, source, scenario, candidate_id):
    base, quote = snapshot["context"], source["quote"]
    profile, cargo = source["profile"], base["cargo_snapshot"]
    route = path_snapshot(source["dataset"], source["template"], profile, cargo)
    timed = timing(route, snapshot["planning_intent"], scenario)
    depart, arrival, completion = [
        datetime.fromisoformat(timed[k])
        for k in ("estimated_departure_at", "estimated_arrival_at", "estimated_completion_at")
    ]
    at = datetime.fromisoformat(snapshot["evaluated_as_of"])
    corridor_impact = None
    if source.get("corridor_projection"):
        from app.corridor.impact import assess as assess_corridor
        from app.corridor.impact import sections

        corridor_impact = assess_corridor(
            sections(
                source["dataset"],
                route,
                timed["estimated_departure_at"],
                source["profile"].get("speed_cap_kph"),
                snapshot["planning_intent"]["planned_stop_seconds"],
            ),
            {**source["corridor_projection"], "evaluated_as_of": at.isoformat()},
        )
    declaration = profile["vehicle_declarations"]
    checks = [
        requirement(
            "PRE_PICKUP",
            base["movement_status"] == "NOT_STARTED" and base["planning_status"] != "CANCELLED",
            "Only unpicked, uncancelled consignments can be planned.",
        ),
        requirement(
            "PAYLOAD_CAPACITY",
            Decimal(cargo["gross_weight_kg"])
            <= Decimal(declaration["declared_payload_capacity_kg"]),
            "Cargo gross weight is compared with payload capacity, not truck tare.",
        ),
        requirement(
            "ROUTE_RESTRICTIONS",
            True
            if route["restriction_assessment"] == "PASS"
            else False
            if route["restriction_assessment"] == "FAIL"
            else None,
            "Missing vehicle measurements or unassessed restrictions need input.",
            route["restriction_notices"],
        ),
        requirement(
            "KNOWN_CORRIDOR",
            None if route["state_sequence"] is None else True,
            "Intermediate states must come from retained topology; state reentry is preserved.",
        ),
        requirement(
            "CURRENT_FIRM_OFFER",
            quote["offer_kind"] == "FIRM_OFFER"
            and datetime.fromisoformat(quote["valid_from"])
            <= at
            < datetime.fromisoformat(quote["accept_by"])
            and source["quote_lifecycle"] == "SUBMITTED",
            "Only current firm, unwithdrawn offers can be ranked.",
        ),
        requirement(
            "RETAINED_DATASET",
            source["dataset_current"],
            "Dataset must be independently published, current and retainable "
            "through the intended use.",
        ),
        requirement(
            "CURRENT_PROFILE",
            source["profile_current"],
            "Routing profile and vehicle declarations must match their current heads.",
        ),
        requirement(
            "SERVICE_WINDOW",
            datetime.fromisoformat(quote["offered_pickup_window_start"])
            <= datetime.fromisoformat(snapshot["planning_intent"]["intended_pickup_at"])
            <= depart
            < datetime.fromisoformat(quote["offered_pickup_window_end"])
            and datetime.fromisoformat(quote["offered_delivery_window_start"])
            <= arrival
            <= datetime.fromisoformat(quote["offered_delivery_window_end"]),
            "Pickup, departure and physical arrival must fit the carrier's service windows.",
        ),
        requirement(
            "BOOKING_WINDOW",
            datetime.fromisoformat(quote["booking_window_start"])
            <= datetime.fromisoformat(snapshot["planning_intent"]["intended_pickup_at"])
            and completion <= datetime.fromisoformat(quote["booking_window_end"]),
            "Bookings must cover pickup through completion including unloading delay.",
        ),
        requirement(
            "RESOURCE_OBSERVATION",
            source["resource_available"],
            "Availability was observed at evaluation time; this is not a reservation.",
        ),
    ]
    for role in ("pickup", "drop"):
        loc = source[role + "_location"]
        checks.append(
            requirement(
                role.upper() + "_PRECISION",
                loc["precision"]
                in source["dataset"]["planning_policy"]["accepted_location_precisions"]
                and loc["state_coordinate_conflict_resolved"],
                "Baseline application policy requires a confirmed gate "
                "and resolved declared-state position.",
            )
        )
    loaded = route["estimated_loaded_vehicle_weight_kg"]
    authorised = profile["maximum_authorised_combined_weight_kg"]
    checks.append(
        requirement(
            "AUTHORISED_COMBINED_WEIGHT",
            None
            if loaded is None or authorised is None
            else Decimal(loaded) <= Decimal(authorised),
            "Combined tare including trailers plus cargo must not exceed authorised weight.",
            loaded,
            authorised,
        )
    )
    if cargo.get("volume_m3") is not None:
        capacity = declaration.get("declared_volume_capacity_m3")
        checks.append(
            requirement(
                "VOLUME_CAPACITY",
                None if capacity is None else Decimal(cargo["volume_m3"]) <= Decimal(capacity),
                "Declared cargo volume must fit known volume capacity.",
            )
        )
    for item in cargo["items"]:
        flags = item["cargo"]
        if flags.get("hazardous_declared"):
            checks.append(
                requirement(
                    "HAZARDOUS_CAPABILITY",
                    declaration.get("declared_hazardous_capable") is True,
                    "Vehicle capability must cover declared hazardous cargo.",
                )
            )
        if flags.get("temperature_controlled"):
            supported = (
                declaration.get("refrigerated") is True
                and declaration.get("temperature_min_c") is not None
                and declaration.get("temperature_max_c") is not None
                and Decimal(declaration["temperature_min_c"]) <= Decimal(flags["temperature_min_c"])
                and Decimal(declaration["temperature_max_c"]) >= Decimal(flags["temperature_max_c"])
            )
            checks.append(
                requirement(
                    "TEMPERATURE_CAPABILITY",
                    supported,
                    "Vehicle declared range must cover every cargo line.",
                )
            )
    permits = source["permit_coverage"]
    corridor = route["state_sequence"]
    cover = (
        None
        if not corridor or not permits.get("covered_states")
        else True
        if set(corridor) <= set(permits["covered_states"])
        else None
    )
    checks.append(
        requirement(
            "CORRIDOR_PERMIT_COVERAGE",
            cover,
            "Reviewed nominated-vehicle permit evidence must cover the corridor; "
            "missing coverage is not unrestricted.",
            permits,
            corridor,
            permits.get("source_refs"),
        )
    )
    for reference in permits.get("source_refs", []):
        checks.append(
            requirement(
                "PERMIT_SERVICE_VALIDITY",
                arrival < datetime.fromisoformat(reference["valid_until"]),
                "Permit evidence must remain valid through estimated physical arrival.",
                arrival.isoformat(),
                reference,
            )
        )
    for key in ["valid_until", "retention_until"]:
        end = source["dataset"].get(key)
        if end:
            checks.append(
                requirement(
                    "ROUTE_SOURCE_USE_WINDOW",
                    completion < datetime.fromisoformat(end),
                    "Operational source must remain current and retainable through planned use.",
                    completion.isoformat(),
                    end,
                )
            )
    deadline = snapshot["deadline"]
    if deadline["at"]:
        checks.append(
            requirement(
                "ARRIVAL_DEADLINE",
                arrival <= datetime.fromisoformat(deadline["at"]),
                "Estimated arrival must meet its explicit deadline basis, "
                "not an inferred bilateral promise.",
                arrival.isoformat(),
                deadline,
            )
        )
    for boundary in source.get("document_planning_deadlines", []):
        checks.append(
            requirement(
                "DOCUMENT_PLANNING_DEADLINE",
                arrival < datetime.fromisoformat(boundary["timestamp"]),
                "Application planning guard for expected arrival; "
                "this does not claim the document has already expired.",
                arrival.isoformat(),
                boundary,
            )
        )
    hypothetical = deepcopy(source["compliance_inputs"])
    hypothetical["facts"]["expected_arrival_at"] = arrival.isoformat()
    hypothetical["facts"]["declared_transit_state_codes"] = corridor[1:-1] if corridor else None
    # Existing vehicle-bound release evidence is never transferred to a hypothetical offer.
    for name in (
        "ewb_identity",
        "ewb_validity",
        "ewb_arrival_window",
        "transport_assurance",
        "loading_manifest",
    ):
        hypothetical["proof"][name] = None
    compliance = []
    for rule in source["compliance_rules"]:
        applies = evaluate(rule["applicability_expression"], hypothetical)
        outcome = (
            evaluate(rule["satisfaction_expression"], hypothetical)
            if applies is not False
            else True
        )
        compliance.append(
            {
                "rule_code": rule["rule_code"],
                "rule_version": rule["rule_version"],
                "class": rule["class"],
                "applicability": "APPLICABLE"
                if applies is True
                else "NOT_APPLICABLE"
                if applies is False
                else "UNKNOWN",
                "outcome": "PASS" if outcome is True else "FAIL" if outcome is False else "UNKNOWN",
                "category": "POST_SELECTION_RELEASE_PREREQUISITE",
                "source_refs": rule["source_ids"],
                "explanation": rule["explanation_template"],
            }
        )
    scope = base["inherited"]
    checks.append(
        requirement(
            "PHASE4_CORRIDOR_SCOPE",
            True if corridor in source["compliance_supported_corridors"] else None,
            "Full corridor needs published Phase 4 coverage; "
            "unknown coverage requires reviewed scope extension.",
        )
    )
    checks.append(
        requirement(
            "PHASE4_GOODS_PROFILE",
            source["compliance_profile_supported"],
            "The declared goods/profile must be supported by the published Phase 4 policy.",
        )
    )
    supported = (
        source["compliance_scope_supported"]
        and scope["transport_mode"] == "ROAD"
        and scope["scope"] == "DOMESTIC_INTERSTATE"
        and scope["currency"] == "INR"
    )
    checks.append(
        requirement(
            "PHASE4_SUPPORTED_SCOPE",
            supported,
            "Only the currently published Phase 4 ordinary-goods road scope is supported.",
        )
    )
    outcomes = [c["outcome"] for c in checks]
    if corridor_impact:
        checks.append(
            requirement(
                "CORRIDOR_OPERATIONAL_IMPACT",
                False
                if corridor_impact["outcome"] == "BLOCKED"
                else None
                if corridor_impact["outcome"] == "NEEDS_REVIEW"
                else True,
                "Current reviewed corridor events, traversal windows and checked source coverage.",
                refs=[
                    {
                        "event_revision_id": i["event_revision_id"],
                        "policy_revision_id": i["policy_revision_id"],
                    }
                    for i in corridor_impact["items"]
                ],
            )
        )
        outcomes = [c["outcome"] for c in checks]
    supported = supported and source["compliance_profile_supported"] is not False
    planning = (
        "UNSUPPORTED"
        if not supported
        else "BLOCKED"
        if "FAIL" in outcomes
        else "NEEDS_INPUT"
        if "UNKNOWN" in outcomes
        else "SUPPORTED_PLAN"
    )
    calculated = cost(
        quote,
        source["quote_revision_id"],
        route,
        cargo,
        snapshot["cost_assumptions"],
        snapshot["comparison_policy"],
        scenario,
        at,
    )
    eligible = (
        planning == "SUPPORTED_PLAN"
        and calculated["cost_completeness"] == "COMPLETE_FOR_COMPARISON"
    )
    return {
        "candidate_id": candidate_id,
        "corridor_impact": corridor_impact,
        "scenario_code": scenario["scenario_code"],
        "assumptions": scenario,
        "assumption_hash": source["scenario_hashes"][scenario["scenario_code"]],
        "route": route,
        **timed,
        "cost": calculated,
        "planning_outcome": planning,
        "planning_constraint_results": checks,
        "candidate_compliance_results": compliance,
        "post_selection_actions": POST_SELECTION,
        "ranking_eligibility": "RANKABLE" if eligible else "NOT_RANKABLE",
        "why_excluded": [c["requirement_code"] for c in checks if c["outcome"] != "PASS"]
        + (
            ["COST_INCOMPLETE"]
            if calculated["cost_completeness"] != "COMPLETE_FOR_COMPARISON"
            else []
        ),
        "informational_limitations": LIMITATIONS
        + ["Travel-time estimate held constant for this scenario."],
        "current_assignment_dispatch_readiness": "SEPARATE_PHASE4_ASSESSMENT",
    }
