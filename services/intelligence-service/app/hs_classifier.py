import json
from difflib import SequenceMatcher
from pathlib import Path

from app.config import settings
from app.llm_gateway import LLMGateway
from app.schemas import HSClassificationRequest, HSClassificationResponse, HSCodeRecommendation

DATA_DIR = Path(__file__).resolve().parent / "data"


def classify_hs_code(
    payload: HSClassificationRequest,
    gateway: LLMGateway,
) -> HSClassificationResponse:
    taxonomy = load_taxonomy()
    query = f"{payload.product_name} {payload.product_description}".lower()
    hints = gateway.classification_hints(payload.product_name, payload.product_description)

    scored_items = []
    for item in taxonomy:
        matched_terms = matching_terms(query, hints, item["keywords"])
        keyword_score = len(matched_terms) / max(len(item["keywords"]), 1)
        title_score = SequenceMatcher(None, query, item["title"].lower()).ratio()
        confidence = min(0.99, round(0.18 + keyword_score * 0.68 + title_score * 0.18, 2))
        scored_items.append((confidence, matched_terms, item))

    scored_items.sort(key=lambda scored: (-scored[0], scored[2]["hs_code"]))
    recommendations = [
        HSCodeRecommendation(
            hs_code=item["hs_code"],
            title=item["title"],
            confidence=confidence,
            human_review_required=confidence < settings.hs_confidence_threshold,
            tariff_notes=item["tariff_notes"],
            matched_terms=matched_terms,
        )
        for confidence, matched_terms, item in scored_items[:3]
    ]

    return HSClassificationResponse(
        provider=gateway.name,
        model=gateway.model,
        confidence_threshold=settings.hs_confidence_threshold,
        recommendations=recommendations,
    )


def load_taxonomy() -> list[dict]:
    return json.loads((DATA_DIR / "tariff_taxonomy.json").read_text(encoding="utf-8"))


def matching_terms(query: str, hints: list[str], keywords: list[str]) -> list[str]:
    haystack = f"{query} {' '.join(hints)}"
    matches = []
    for keyword in keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in haystack:
            matches.append(keyword)
    return matches
