"""Generate the Phase 1 Postman collection and OpenAPI from the shared validators."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("NEO4J_ENABLED", "false")
os.environ.setdefault("SEED_DEMO_DATA", "false")
sys.path.insert(0, str(ROOT / "services/shipment-service"))

from app.main import app  # noqa: E402
from app.trades.demo import demo_address, demo_facts, demo_profile  # noqa: E402


def main():
    schema = app.openapi()
    output = ROOT / "docs/postman"
    output.mkdir(parents=True, exist_ok=True)
    collection = {
        "info": {
            "name": "TradeTwin Commercial Agreements Phase 1",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": (
                "Existing OAuth sessions only. Set current_organization_id and "
                "profile_token per actor. Use fresh idempotency keys for new intent, "
                "preserve keys for retries; ETags include quotes. "
                "Never use mock identity headers against production."
            ),
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{profile_token}}", "type": "string"}],
        },
        "variable": [
            {"key": key, "value": value}
            for key, value in {
                "base_url": "http://localhost:8011",
                "profile_token": "",
                "current_organization_id": "",
                "seller_organization_id": "",
                "buyer_organization_id": "",
                "trade_id": "",
                "offer_id": "",
                "amendment_id": "",
                "organization_id": "",
                "member_user_id": "",
                "revision_id": "",
                "base_accepted_revision_id": "",
                "terms_hash": "",
                "etag": '"1"',
                "idempotency_key": "replace-with-a-unique-key",
                "commercial_valid_until": "",
                "pickup_earliest_at": "",
                "pickup_latest_at": "",
                "delivery_deadline_at": "",
            }.items()
        ],
        "item": [],
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "const offsets = {commercial_valid_until: 7, pickup_earliest_at: 1,",
                        "pickup_latest_at: 2, delivery_deadline_at: 4};",
                        "for (const [key, days] of Object.entries(offsets)) {",
                        "if (!pm.collectionVariables.get(key)) pm.collectionVariables.set(key,",
                        "new Date(Date.now() + days * 86400000).toISOString()); }",
                    ],
                },
            }
        ],
    }
    facts = demo_facts("{{seller_organization_id}}", "{{buyer_organization_id}}")
    facts["commercial_terms"]["commercial_valid_until"] = "{{commercial_valid_until}}"
    for key in ("pickup_earliest_at", "pickup_latest_at", "delivery_deadline_at"):
        facts["delivery_requirements"][key] = "{{" + key + "}}"
    bodies = {
        "POST /api/v1/organizations": demo_profile(
            "Example business (declaration)", demo_address()
        ),
        "PATCH /api/v1/organizations/{organization_id}": {"trade_name": "Example trading name"},
        "POST /api/v1/organizations/{organization_id}/registrations": {
            "gstin": "33ABCDE1234F1Z7",
            "state_code": "33",
            "declared_taxpayer_scheme": "UNKNOWN",
            "declared_establishment_kind": "UNKNOWN",
        },
        "POST /api/v1/organizations/{organization_id}/locations": {
            "label": "Warehouse",
            "location_type": "WAREHOUSE",
            "address": demo_address(),
            "visibility": "PRIVATE",
        },
        "POST /api/v1/organizations/{organization_id}/members": {
            "user_id": "{{member_user_id}}",
            "capabilities": ["SELLER_OPERATOR"],
            "status": "ACTIVE",
        },
        "POST /api/v1/trades": {"initiated_by_role": "SELLER", "facts": facts},
    }
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in operations.items():
            name = f"{method.upper()} {path}"
            url = "{{base_url}}" + path
            for parameter in operation.get("parameters", []):
                if parameter["in"] == "path":
                    url = url.replace(
                        "{" + parameter["name"] + "}", "{{" + parameter["name"] + "}}"
                    )
            if path == "/api/v1/trades":
                if method == "get":
                    url += "?role=SELLER"
            if path == "/api/v1/trading-partners":
                url += "?q=Demo"
            headers = [{"key": "X-Organization-Id", "value": "{{current_organization_id}}"}]
            body = bodies.get(name)
            if method in {"post", "patch"}:
                headers.extend(
                    [
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "Idempotency-Key", "value": "{{idempotency_key}}"},
                    ]
                )
                if any(item["name"] == "If-Match" for item in operation.get("parameters", [])):
                    headers.append({"key": "If-Match", "value": "{{etag}}"})
                if body is None:
                    if path.endswith("/draft"):
                        body = {
                            "base_revision_id": "{{revision_id}}",
                            "changes": {"tax_terms": "Updated agreed declaration"},
                        }
                    elif path.endswith("/offers"):
                        body = {
                            "revision_id": "{{revision_id}}",
                            "commercial_valid_until": facts["commercial_terms"][
                                "commercial_valid_until"
                            ],
                        }
                    elif path.endswith("/amendments"):
                        body = {
                            "base_accepted_revision_id": "{{base_accepted_revision_id}}",
                            "reason": "Change agreed quantity",
                        }
                    elif path.endswith(("/confirmations", "/rejections")):
                        body = {"revision_id": "{{revision_id}}", "terms_hash": "{{terms_hash}}"}
                        if path.endswith("/rejections"):
                            body["reason"] = "Terms need revision"
                    else:
                        body = {"reason": "Withdraw proposal"}
            request = {"method": method.upper(), "url": url, "header": headers}
            if body is not None:
                request["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(body, indent=2),
                    "options": {"raw": {"language": "json"}},
                }
            scripts = []
            if path == "/api/v1/trades" and method == "post":
                scripts = [
                    "if (pm.response.code === 201) {",
                    "const r = pm.response.json();",
                    "pm.collectionVariables.set('trade_id', r.trade_id);",
                    "pm.collectionVariables.set('revision_id', r.current_revision_id);",
                    "pm.collectionVariables.set('etag', r.etag); }",
                ]
            elif method in {"get", "patch", "post"} and (
                "/trades/" in path or "/amendments/" in path or "/offers/" in path
            ):
                scripts = [
                    "if (pm.response.code < 300) { const r = pm.response.json();",
                    "const v = pm.collectionVariables;",
                    "if(r.etag) v.set('etag', r.etag);",
                    "if(r.current_revision_id) v.set('revision_id', r.current_revision_id);",
                    "if(r.accepted_revision) v.set('base_accepted_revision_id',",
                    "r.accepted_revision.id);",
                    "if(r.accepted_revision_id) v.set('base_accepted_revision_id',",
                    "r.accepted_revision_id);",
                    "if(r.active_offer) {",
                    "pm.collectionVariables.set('offer_id',r.active_offer.id);",
                    "pm.collectionVariables.set('revision_id',r.active_offer.revision_id);",
                    "pm.collectionVariables.set('terms_hash',r.active_offer.terms_hash); }",
                    "if(r.pending_amendment) v.set('amendment_id',r.pending_amendment.id); }",
                ]
            collection["item"].append(
                {
                    "name": name,
                    "request": request,
                    "event": [
                        {"listen": "test", "script": {"type": "text/javascript", "exec": scripts}}
                    ]
                    if scripts
                    else [],
                }
            )
    (output / "commercial-agreements.postman_collection.json").write_text(
        json.dumps(collection, indent=2) + "\n", encoding="utf-8"
    )
    (output / "commercial-agreements.openapi.json").write_text(
        json.dumps(schema, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Generated {len(collection['item'])} Phase 1 Postman requests and shared OpenAPI schemas"
    )


if __name__ == "__main__":
    main()
