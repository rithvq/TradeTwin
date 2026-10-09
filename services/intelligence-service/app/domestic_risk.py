"""Reproducible synthetic domestic transport baseline; no measured accuracy claim."""

from functools import lru_cache

from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

FEATURES = ("distance_km", "stop_count", "total_value_inr", "missing_hsn_count")


@lru_cache(maxsize=1)
def models():
    # Enumerated synthetic scenarios keep the generator and labels inspectable.
    rows, reviews, exceptions, delays = [], [], [], []
    for distance in (50, 200, 500, 1000, 1800):
        for stops in (1, 2, 4):
            for value in (20000, 75000, 300000):
                for missing in (0, 1, 2):
                    rows.append([distance, stops, value, missing])
                    reviews.append(int(missing > 0 or value >= 300000))
                    exceptions.append(int(missing >= 2))
                    delays.append(round(stops * 0.5 + missing * 2 + distance / 1000, 1))
    fitted = [
        RandomForestClassifier(n_estimators=80, random_state=42),
        RandomForestClassifier(n_estimators=80, random_state=43),
        RandomForestRegressor(n_estimators=80, random_state=44),
    ]
    for model, target in zip(fitted, (reviews, exceptions, delays), strict=True):
        model.fit(rows, target)
    return fitted


def score_domestic(shipment):
    items = shipment.get("consignments", [])
    legs = shipment.get("route_legs", [])
    features = dict(
        zip(
            FEATURES,
            (
                sum((leg.get("domestic") or {}).get("distance_km", 0) for leg in legs),
                len(legs),
                sum((item.get("domestic") or {}).get("consignment_value", 0) for item in items),
                sum(not item.get("proposed_hs_code") for item in items),
            ),
            strict=True,
        )
    )
    vector = [[features[key] for key in FEATURES]]
    review, exception, delay = models()
    review_probability = float(review.predict_proba(vector)[0][1])
    exception_probability = float(exception.predict_proba(vector)[0][1])
    return dict(
        model_version="domestic-synthetic-v1",
        features=features,
        inspection_probability=round(review_probability, 3),
        rejection_probability=round(exception_probability, 3),
        expected_clearance_delay_hours=round(float(delay.predict(vector)[0]), 1),
        risk_level="HIGH"
        if exception_probability >= 0.5
        else "MEDIUM"
        if review_probability >= 0.5
        else "LOW",
        warning=(
            "Prototype prediction based on synthetic or organization-provided data. "
            "Domestic outputs describe simulated document review, exceptions and "
            "handling delay; accuracy is unvalidated."
        ),
        risk_factors=[
            dict(
                factor=key.replace("_", " ").title(),
                impact=str(value),
                explanation="Input to the synthetic domestic baseline; not a causal explanation.",
            )
            for key, value in features.items()
        ],
    )
