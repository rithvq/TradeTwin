"""Transparent finite-candidate multi-objective ranking, never a claim of global optimality."""

from fractions import Fraction

from app.trades.terms import digest

ENGINE_VERSION = "INDIA_FREIGHT_MULTICRITERIA_1"
FACTOR_UNITS = {
    "distance": "metres",
    "duration": "mapped driving plus declared stop seconds, excludes uncertain delay",
    "road_weather_exposure": "observed exposure index, not incident probability",
    "state_transit_history": "observed excess seconds on this directed state corridor",
    "toll_exposure": "mapped toll-road metres, not toll rupees",
}


def compare(candidates, weights):
    eligible = [c for c in candidates if c["feasibility"] != "EXCLUDED"]
    # Use the same known dimensions for EVERY compared route. Missing evidence is
    # not zero risk and never becomes a score advantage for a less-observed route.
    active = [
        name
        for name, weight in weights.items()
        if weight and eligible and all(c["metrics"].get(name) is not None for c in eligible)
    ]
    omitted = [name for name, weight in weights.items() if weight and name not in active]
    if not eligible or not active:
        return {
            "best_candidate_id": None,
            "rankings": [],
            "active_factors": active,
            "omitted_factors": omitted,
            "comparison_status": "INSUFFICIENT_DATA",
        }
    total = sum(weights[name] for name in active)
    bounds = {
        name: (min(c["metrics"][name] for c in eligible), max(c["metrics"][name] for c in eligible))
        for name in active
    }
    rows = []
    for candidate in eligible:
        contributions = []
        score = Fraction(0)
        for name in active:
            lo, hi = bounds[name]
            loss = (
                Fraction(str(candidate["metrics"][name] - lo)) / Fraction(str(hi - lo))
                if hi != lo
                else Fraction(0)
            )
            part = loss * Fraction(weights[name], total)
            score += part
            contributions.append(
                {
                    "factor": name,
                    "value": candidate["metrics"][name],
                    "unit": FACTOR_UNITS[name],
                    "minimum": lo,
                    "maximum": hi,
                    "effective_weight_percent": round(100 * weights[name] / total, 3),
                    "weighted_loss": round(float(part), 6),
                }
            )
        dominated = any(
            all(other["metrics"][name] <= candidate["metrics"][name] for name in active)
            and any(other["metrics"][name] < candidate["metrics"][name] for name in active)
            for other in eligible
        )
        rows.append(
            (
                score,
                candidate["driving_seconds"],
                candidate["id"],
                {
                    "candidate_id": candidate["id"],
                    "score": round(float(score), 6),
                    "score_numerator": str(score.numerator),
                    "score_denominator": str(score.denominator),
                    "pareto_member": not dominated,
                    "contributions": contributions,
                },
            )
        )
    ranked = [{**row, "rank": index + 1} for index, (_, _, _, row) in enumerate(sorted(rows))]
    best = next(c for c in eligible if c["id"] == ranked[0]["candidate_id"])
    for candidate in candidates:
        candidate["comparison_to_best"] = {
            "distance_delta_m": candidate["metrics"]["distance"] - best["metrics"]["distance"],
            "duration_delta_seconds": candidate["metrics"]["duration"] - best["metrics"]["duration"]
            if candidate["metrics"]["duration"] is not None
            and best["metrics"]["duration"] is not None
            else None,
            "reason_codes": candidate["reason_codes"]
            if candidate["feasibility"] == "EXCLUDED"
            else ["LOWEST_WEIGHTED_LOSS"]
            if candidate["id"] == best["id"]
            else ["HIGHER_WEIGHTED_LOSS_OR_TIE_BREAK"],
        }
    conditional = omitted or any(c["feasibility"] != "ASSESSED" for c in eligible)
    return {
        "best_candidate_id": best["id"],
        "rankings": ranked,
        "active_factors": active,
        "omitted_factors": omitted,
        "comparison_status": "SINGLE_CANDIDATE"
        if len(eligible) == 1
        else "CONDITIONAL"
        if conditional
        else "ASSESSED",
        "method": "Hard exclusions, common observed dimensions, weighted min-max loss, "
        "deterministic tie break.",
        "candidate_set_hash": digest([c["id"] for c in candidates]),
        "notice": (
            "Only one eligible route was returned; superiority over other roads is unproven. "
            if len(eligible) == 1
            else "Best among these compared routes under the displayed weights and evidence. "
        )
        + "Not a global optimum, safety guarantee, freight quote or dispatch authorization.",
    }
