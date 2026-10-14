"""Scoping must retain transitive references without inheriting later-phase API paths."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_schema import prune, scoped  # noqa: E402


def fixture():
    return {
        "paths": {
            "/commercial": {
                "get": {
                    "tags": ["Commercial agreements"],
                    "schema": {"$ref": "#/components/schemas/A"},
                }
            },
            "/product": {
                "get": {
                    "tags": ["Commercial agreements", "Product integration - Phase 7"],
                    "schema": {"$ref": "#/components/schemas/C"},
                }
            },
        },
        "components": {
            "schemas": {
                "A": {"items": {"$ref": "#/components/schemas/B"}},
                "B": {"type": "string"},
                "C": {"type": "number"},
            }
        },
    }


def test_commercial_does_not_inherit_product():
    result = scoped(fixture(), {"Commercial agreements"})
    assert set(result["paths"]) == {"/commercial"}
    assert set(result["components"]["schemas"]) == {"A", "B"}


def test_product_is_transitively_complete():
    result = scoped(fixture(), {"Product integration - Phase 7"})
    assert set(result["paths"]) == {"/product"}
    assert set(result["components"]["schemas"]) == {"C"}


def test_pruning_does_not_mutate_input():
    original = fixture()
    result = prune(original)
    result["components"]["schemas"].clear()
    assert len(original["components"]["schemas"]) == 3
