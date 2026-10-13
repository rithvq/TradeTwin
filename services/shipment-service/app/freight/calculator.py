"""Pure exact paise, scenario timing and rational rankings. No tax-rate inference."""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

from app.operations.access import fail

ENGINE_VERSION = "TRADETWIN_BASELINE_1.0"
LIMITATIONS = [
    "Gross cash-outlay comparison under declared assumptions, not a final tax calculation.",
    "Estimated travel time; static traffic, not guaranteed arrival.",
    "Availability at check is not a reservation.",
    "Fresh actual Phase 4 release is required after commitment.",
]


def quote_totals(quote):
    subtotal = sum(int(c["amount_minor"]) for c in quote["charge_components"])
    discount = int(quote["discount_minor"])
    if discount > subtotal:
        fail("VALIDATION_ERROR", "Discount exceeds fixed component subtotal.", status=422)
    net = subtotal - discount
    tax = quote["carrier_charged_tax_minor"]
    if net >= 2**63 or (tax is not None and net + int(tax) >= 2**63):
        fail(
            "VALIDATION_ERROR",
            "Carrier amount exceeds supported integer paise storage.",
            status=422,
        )
    return net, int(tax) if tax is not None else None, net + int(tax) if tax is not None else None


def contingent(term, wait):
    minutes = max(0, wait - term["free_minutes"])
    increment = term["billing_increment_minutes"]
    count = (minutes + increment - 1) // increment
    amount = count * int(term["charge_per_increment_gross_minor"])
    cap = term.get("maximum_charge_gross_minor")
    return min(amount, int(cap)) if cap is not None else amount


def timing(route, intent, scenario):
    departure = datetime.fromisoformat(intent["intended_departure_at"])
    delay = scenario["additional_wait_minutes"] + scenario["additional_stop_minutes"]
    origin = delay if scenario["delay_placement"] == "ORIGIN_BEFORE_DEPARTURE" else 0
    transit = delay if scenario["delay_placement"] == "IN_TRANSIT" else 0
    unloading = delay if scenario["delay_placement"] == "DESTINATION_UNLOADING" else 0
    shifted = departure + timedelta(minutes=origin)
    arrival = shifted + timedelta(
        seconds=route["estimated_driving_seconds"] + intent["planned_stop_seconds"], minutes=transit
    )
    return {
        "estimated_departure_at": shifted.isoformat(),
        "estimated_arrival_at": arrival.isoformat(),
        "estimated_completion_at": (arrival + timedelta(minutes=unloading)).isoformat(),
        "travel_time_held_constant": True,
    }


def cost(quote, quote_id, route, cargo, assumptions, policy, scenario, as_of):
    net, tax, payable = quote_totals(quote)
    unknown, steps, refs, external = [], [], [], 0
    if payable is None:
        unknown.append("CARRIER_TAX")
    steps.append(
        {
            "origin": "QUOTE",
            "component_code": "CARRIER_PAYABLE",
            "amount_minor": str(payable) if payable is not None else None,
            "calculation": {
                "net_minor": str(net),
                "discount_minor": quote["discount_minor"],
                "tax_minor": str(tax) if tax is not None else None,
            },
        }
    )
    coverage = {c["category_code"]: c["coverage"] for c in quote["service_coverage"]}
    selected = [
        c
        for c in (assumptions or {}).get("external_cost_components", [])
        if quote_id in c["applies_to_quote_revision_ids"]
    ]
    valid_categories, estimates = set(), False
    for component in selected:
        category = component["category"]
        if coverage.get(category) in {"INCLUDED_IN_QUOTED_PRICE", "NOT_APPLICABLE"}:
            fail(
                "COST_CATEGORY_DUPLICATED",
                "Included/not-applicable categories cannot also be charged externally.",
                status=422,
            )
        valid = component.get("amount_includes_applicable_tax") is True and (
            not component.get("valid_until")
            or as_of < datetime.fromisoformat(component["valid_until"])
        )
        if policy == "QUOTED_AMOUNTS_ONLY" and component["source_kind"] not in {
            "REVIEWED_EXTERNAL_OFFER",
            "SIMULATION",
        }:
            valid = False
        amount = None
        with localcontext() as ctx:
            ctx.prec = 60
            if component["basis"] == "FIXED":
                if component.get("fixed_amount_minor") is not None:
                    amount = int(component["fixed_amount_minor"])
            elif component.get("rate_minor_per_unit") is not None:
                sources = {
                    "ROUTE_DISTANCE_KM": Decimal(route["distance_meters"]) / 1000,
                    "CARGO_GROSS_KG": Decimal(cargo["gross_weight_kg"]),
                    "PACKAGE_COUNT": Decimal(cargo["package_count"]),
                    "FIXED": Decimal(component["fixed_quantity"])
                    if component.get("fixed_quantity") is not None
                    else None,
                }
                expected = {
                    "PER_KM": "ROUTE_DISTANCE_KM",
                    "PER_KG": "CARGO_GROSS_KG",
                    "PER_PACKAGE": "PACKAGE_COUNT",
                }[component["basis"]]
                quantity = sources[component["quantity_source"]]
                if quantity is not None and component["quantity_source"] == expected:
                    amount = int(
                        (Decimal(component["rate_minor_per_unit"]) * quantity).quantize(
                            Decimal(1), rounding=ROUND_HALF_UP
                        )
                    )
        if valid and amount is not None:
            external += amount
            valid_categories.add(category)
            estimates = estimates or component["source_kind"] in {
                "USER_ESTIMATE",
                "LICENSED_DATA",
                "SIMULATION",
            }
        else:
            unknown.append(category)
            amount = None
        steps.append(
            {
                "origin": "EXTERNAL_ASSUMPTION",
                "component_code": category,
                "amount_minor": str(amount) if amount is not None else None,
                "calculation": component,
                "rounding": "HALF_UP_ONCE",
            }
        )
        refs.append(component.get("source_reference"))
    for category, state in coverage.items():
        if state == "UNKNOWN" or (
            state == "EXCLUDED_PAYER_COST" and category not in valid_categories
        ):
            unknown.append(category)
    recipient_tax = 0
    if quote["tax_treatment"] == "DECLARED_RECIPIENT_ACCOUNTED":
        declaration = next(
            (
                t
                for t in (assumptions or {}).get("recipient_tax_cash_estimates", [])
                if t["quote_revision_id"] == quote_id
            ),
            None,
        )
        if not declaration or declaration["amount_minor"] is None:
            unknown.append("RECIPIENT_ACCOUNTED_TAX")
        else:
            recipient_tax = int(declaration["amount_minor"])
            estimates = True
            if policy == "QUOTED_AMOUNTS_ONLY":
                unknown.append("RECIPIENT_TAX_ESTIMATE_DISALLOWED")
    extra = 0
    placement = scenario["delay_placement"]
    if scenario["additional_wait_minutes"] and placement != "IN_TRANSIT":
        code = "ORIGIN_WAIT" if placement == "ORIGIN_BEFORE_DEPARTURE" else "DESTINATION_WAIT"
        term = next((t for t in quote["contingent_charge_terms"] if t["code"] == code), None)
        if term is None:
            unknown.append(code)
        else:
            extra = contingent(term, scenario["additional_wait_minutes"])
            steps.append(
                {
                    "origin": "CONTINGENT_TERM",
                    "component_code": code,
                    "amount_minor": str(extra),
                    "calculation": {"wait_minutes": scenario["additional_wait_minutes"], **term},
                }
            )
    partial = (payable if payable is not None else net) + external + recipient_tax + extra
    if partial >= 2**63:
        fail(
            "VALIDATION_ERROR",
            "Comparison total exceeds supported integer paise storage.",
            status=422,
        )
    return {
        "carrier_net_minor": str(net),
        "carrier_charged_tax_minor": str(tax) if tax is not None else None,
        "carrier_payable_minor": str(payable) if payable is not None else None,
        "external_cost_minor": str(external),
        "recipient_tax_cash_estimate_minor": str(recipient_tax),
        "scenario_contingent_charge_minor": str(extra),
        "known_partial_subtotal_minor": str(partial),
        "comparison_total_minor": None if unknown else str(partial),
        "cost_completeness": "INCOMPLETE" if unknown else "COMPLETE_FOR_COMPARISON",
        "price_basis": "INCOMPLETE" if unknown else "MIXED" if estimates else "QUOTED_FIXED",
        "unknown_cost_categories": sorted(set(unknown)),
        "calculation_steps": steps,
        "source_refs": refs,
        "limitations": LIMITATIONS,
    }


def rank(candidates, scenario_code, objective, weights):
    eligible = [
        (c, c["scenarios"][scenario_code])
        for c in candidates
        if c["scenarios"][scenario_code]["ranking_eligibility"] == "RANKABLE"
    ]
    if not eligible:
        return []
    values = {
        c["candidate_id"]: (
            int(s["cost"]["comparison_total_minor"]),
            datetime.fromisoformat(s["estimated_arrival_at"]),
        )
        for c, s in eligible
    }
    costs = [v[0] for v in values.values()]
    times = [v[1] for v in values.values()]
    lo, hi, early, late = min(costs), max(costs), min(times), max(times)
    time_range = (late - early) // timedelta(microseconds=1)
    rows = []
    for c, _ in eligible:
        amount, at = values[c["candidate_id"]]
        score = (
            Fraction(amount - lo, hi - lo) * weights["cost_basis_points"]
            if hi != lo
            else Fraction(0)
        )
        if time_range:
            score += (
                Fraction((at - early) // timedelta(microseconds=1), time_range)
                * weights["time_basis_points"]
            )
        key = (
            (amount, at, c["candidate_id"])
            if objective == "LOWEST_COMPARABLE_COST"
            else (at, amount, c["candidate_id"])
            if objective == "EARLIEST_ESTIMATED_ARRIVAL"
            else (score, amount, at, c["candidate_id"])
        )
        dominated = any(
            a <= amount and t <= at and (a < amount or t < at) for a, t in values.values()
        )
        rows.append(
            (
                key,
                {
                    "candidate_id": c["candidate_id"],
                    "scenario_code": scenario_code,
                    "objective": objective,
                    "pareto_member": not dominated,
                    "score_numerator": str(score.numerator),
                    "score_denominator": str(score.denominator),
                    "normalisation": {
                        "minimum_cost_minor": str(lo),
                        "maximum_cost_minor": str(hi),
                        "earliest_arrival": early.isoformat(),
                        "latest_arrival": late.isoformat(),
                    },
                    "explanation": "Eligible firm offer with complete comparable cost; "
                    "ordered only within this candidate set.",
                },
            )
        )
    return [{**row, "rank": i + 1} for i, (_, row) in enumerate(sorted(rows, key=lambda r: r[0]))]
