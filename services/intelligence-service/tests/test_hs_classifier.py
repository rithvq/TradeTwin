# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["LLM_PROVIDER"] = "mock"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.hs_classifier import classify_hs_code
from app.llm_gateway import MockLLMGateway
from app.schemas import HSClassificationRequest


def test_lithium_battery_classification_returns_top_three_with_notes() -> None:
    result = classify_hs_code(
        HSClassificationRequest(
            product_name="Lithium batteries",
            product_description="Rechargeable lithium battery packs",
        ),
        MockLLMGateway(),
    )

    assert len(result.recommendations) == 3
    assert result.recommendations[0].hs_code == "850760"
    assert result.recommendations[0].confidence >= result.confidence_threshold
    assert result.recommendations[0].human_review_required is False
    assert "safety documentation" in result.recommendations[0].tariff_notes


def test_low_confidence_classification_requires_human_review() -> None:
    result = classify_hs_code(
        HSClassificationRequest(
            product_name="General merchandise sample",
            product_description="Mixed item",
        ),
        MockLLMGateway(),
    )

    assert result.recommendations[0].human_review_required is True
