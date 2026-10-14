"""Credential-free Phase 6 foundation contracts; no claim of recovery execution support."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

from contract_schema import prune

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "commercial_contracts", ROOT / "scripts/export-commercial-contracts.py"
)
commercial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commercial)


def main():
    folder = ROOT / "docs/postman"
    document = deepcopy(commercial.app.openapi())
    document["paths"] = {
        path: {
            method: operation
            for method, operation in methods.items()
            if "Corridor intelligence - Phase 6" in operation.get("tags", [])
        }
        for path, methods in document["paths"].items()
    }
    document["paths"] = {path: methods for path, methods in document["paths"].items() if methods}
    document = prune(document)
    (folder / "corridor-intelligence.openapi.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    items = []
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            headers = [{"key": "X-Organization-Id", "value": "{{organization_id}}"}]
            request = {
                "method": method.upper(),
                "url": "{{base_url}}" + path.replace("{ident}", "{{record_id}}"),
                "header": headers,
                "auth": {
                    "type": "bearer",
                    "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}],
                },
            }
            if method == "post":
                headers.extend(
                    [
                        {"key": "Idempotency-Key", "value": "{{$guid}}"},
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "If-Match", "value": "{{current_etag}}"},
                    ]
                )
                request["body"] = {
                    "mode": "raw",
                    "raw": "{{command_json}}",
                    "options": {"raw": {"language": "json"}},
                }
            items.append({"name": operation.get("summary", path), "request": request})
    collection = {
        "info": {
            "name": "TradeTwin corridor intelligence foundation",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": key, "value": value}
            for key, value in {
                "base_url": "http://localhost:8011",
                "organization_id": "",
                "record_id": "",
                "token": "",
                "current_etag": "",
                "command_json": "{}",
            }.items()
        ],
        "item": items,
    }
    (folder / "corridor-intelligence.collection.json").write_text(
        json.dumps(collection, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
