import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from app.schemas import RiskFactor

DATA_DIR = Path(__file__).resolve().parent / "data"
WARNING = "Prototype prediction based on synthetic or organization-provided data."
FEATURE_NAMES = [
    "consignment_count",
    "total_quantity",
    "total_declared_value",
    "route_country_count",
    "has_lithium",
    "has_electronics",
    "transport_mode_sea",
    "includes_uae",
    "unloaded_event_count",
    "missing_hs_count",
]


def score_shipment(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    features = extract_features(shipment, events)
    model = trained_model()
    vector = [[features[name] for name in FEATURE_NAMES]]

    inspection_probability = float(model["inspection"].predict_proba(vector)[0][1])
    rejection_probability = float(model["rejection"].predict_proba(vector)[0][1])
    expected_delay = float(model["delay"].predict(vector)[0])

    return {
        "inspection_probability": round_probability(inspection_probability),
        "rejection_probability": round_probability(rejection_probability),
        "expected_clearance_delay_hours": round(max(expected_delay, 1.0), 1),
        "risk_level": risk_level(inspection_probability, rejection_probability, expected_delay),
        "features": features,
        "risk_factors": [factor.model_dump() for factor in explain_factors(features)],
        "warning": WARNING,
        "model_version": "synthetic-demo-v1",
    }


@lru_cache(maxsize=1)
def trained_model() -> dict[str, Any]:
    rows = json.loads((DATA_DIR / "synthetic_customs_outcomes.json").read_text(encoding="utf-8"))
    x = [[row[name] for name in FEATURE_NAMES] for row in rows]
    inspection_y = [row["inspection"] for row in rows]
    rejection_y = [row["rejection"] for row in rows]
    delay_y = [row["clearance_delay_hours"] for row in rows]

    inspection_model = RandomForestClassifier(n_estimators=80, random_state=42)
    rejection_model = RandomForestClassifier(n_estimators=80, random_state=43)
    delay_model = RandomForestRegressor(n_estimators=80, random_state=44)
    inspection_model.fit(x, inspection_y)
    rejection_model.fit(x, rejection_y)
    delay_model.fit(x, delay_y)

    return {
        "inspection": inspection_model,
        "rejection": rejection_model,
        "delay": delay_model,
    }


def extract_features(
    shipment: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, float]:
    consignments = shipment.get("consignments", [])
    route_countries = countries_on_route(shipment)
    product_text = " ".join(
        f"{item.get('product_name', '')} {item.get('product_description', '')}"
        for item in consignments
    ).lower()

    return {
        "consignment_count": float(len(consignments)),
        "total_quantity": float(sum(float(item.get("quantity") or 0) for item in consignments)),
        "total_declared_value": float(
            sum(float(item.get("declared_value") or 0) for item in consignments)
        ),
        "route_country_count": float(len(route_countries)),
        "has_lithium": 1.0 if "lithium" in product_text and "batter" in product_text else 0.0,
        "has_electronics": 1.0 if "electronics" in product_text else 0.0,
        "transport_mode_sea": 1.0 if shipment.get("transport_mode") == "SEA" else 0.0,
        "includes_uae": 1.0 if "UAE" in route_countries else 0.0,
        "unloaded_event_count": float(
            sum(1 for event in events if event.get("event_type") == "UNLOADED")
        ),
        "missing_hs_count": float(
            sum(1 for item in consignments if not item.get("proposed_hs_code"))
        ),
    }


def explain_factors(features: dict[str, float]) -> list[RiskFactor]:
    factors: list[RiskFactor] = []
    if features["has_lithium"]:
        factors.append(
            RiskFactor(
                factor="Lithium battery cargo",
                impact="Increases inspection probability",
                explanation="Demo data treats lithium battery shipments as requiring extra review.",
            )
        )
    if features["includes_uae"] and features["route_country_count"] > 2:
        factors.append(
            RiskFactor(
                factor="Multi-jurisdiction route through UAE",
                impact="Increases clearance complexity",
                explanation="Transit through UAE adds another procedure path to reconcile.",
            )
        )
    if features["total_declared_value"] >= 40000:
        factors.append(
            RiskFactor(
                factor="Higher declared value",
                impact="Increases valuation review sensitivity",
                explanation=(
                    "The synthetic model assigns higher review likelihood to "
                    "high-value cargo."
                ),
            )
        )
    if features["missing_hs_count"]:
        factors.append(
            RiskFactor(
                factor="Missing proposed HS code",
                impact="Increases rejection probability",
                explanation="Missing classification data leaves rule selection less certain.",
            )
        )
    if features["unloaded_event_count"]:
        factors.append(
            RiskFactor(
                factor="Partial unloading event",
                impact="Increases procedural review",
                explanation="One shipment can contain both import and transit treatments.",
            )
        )
    return factors or [
        RiskFactor(
            factor="Baseline synthetic profile",
            impact="No elevated factor detected",
            explanation="The shipment matches lower-complexity examples in the seeded demo data.",
        )
    ]


def countries_on_route(shipment: dict[str, Any]) -> set[str]:
    countries = {shipment.get("exporter_country"), shipment.get("importer_country")}
    for leg in shipment.get("route_legs", []):
        countries.add(leg.get("origin_country"))
        countries.add(leg.get("destination_country"))
    return {country for country in countries if country}


def risk_level(
    inspection_probability: float,
    rejection_probability: float,
    expected_delay: float,
) -> str:
    if rejection_probability >= 0.35 or inspection_probability >= 0.7 or expected_delay >= 72:
        return "HIGH"
    if rejection_probability >= 0.18 or inspection_probability >= 0.45 or expected_delay >= 36:
        return "MEDIUM"
    return "LOW"


def round_probability(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)
