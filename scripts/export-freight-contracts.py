"""Phase 5 typed API schemas and credential-free Postman request templates."""

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
from app.freight import schemas as s  # noqa: E402
from app.freight_routes.schemas import StudyInput  # noqa: E402


def main():
    folder = ROOT / "docs/postman"
    schema = deepcopy(commercial.app.openapi())
    schema["paths"] = {
        p: {
            m: o
            for m, o in methods.items()
            if set(o.get("tags", []))
            & {"Freight planning - Phase 5", "India freight route intelligence"}
        }
        for p, methods in schema["paths"].items()
    }
    schema["paths"] = {p: m for p, m in schema["paths"].items() if m}
    schema = prune(schema)
    (folder / "freight-planning.openapi.json").write_text(
        json.dumps(schema, indent=2) + "\n", encoding="utf-8"
    )
    for name, model in {
        "ROUTING_LOCATION_V1": s.LocationInput,
        "ROUTING_VEHICLE_PROFILE_V1": s.ProfileInput,
        "DATASET_REVISION_V1": s.DatasetInput,
        "FREIGHT_RFQ_V1": s.RFQInput,
        "FREIGHT_QUOTE_V1": s.QuoteInput,
        "COST_ASSUMPTIONS_V1": s.AssumptionsInput,
        "TRADETWIN_INPUT_V1": s.RunInput,
        "SCENARIO_V1": s.Scenario,
        "TRADETWIN_SELECTION_V1": s.SelectionInput,
        "FREIGHT_CANCELLATION_V1": s.CancellationInput,
        "FREIGHT_ROUTE_STUDY_V1": StudyInput,
    }.items():
        definition = model.model_json_schema(mode="serialization")
        definition["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        definition["description"] = (
            "Phase 5 command fields. Server-derived identity, execution mode "
            "and hashes are never client overrides."
        )
        (folder / f"{name}.schema.json").write_text(
            json.dumps(definition, indent=2) + "\n", encoding="utf-8"
        )
    variables = {
        "base_url": "http://localhost:8011",
        "token": "",
        "organization_id": "",
        "consignment_id": "",
        "vehicle_id": "",
        "rfq_id": "",
        "quote_id": "",
        "run_id": "",
        "route_study_id": "",
        "route_study_json": "{}",
        "selection_id": "",
        "commitment_id": "",
        "cancellation_id": "",
        "assumption_id": "",
        "context_etag": "",
        "head_etag": "",
        "stale_etag": '"0"',
        "location_json": "{}",
        "profile_json": "{}",
        "rfq_json": "{}",
        "quote_json": "{}",
        "assumptions_json": "{}",
        "run_json": "{}",
        "selection_json": "{}",
        "decision_json": "{}",
        "cancellation_json": "{}",
        "scenario_json": "{}",
    }
    items = []

    def add(name, method, path, body=None, etag=None, status=200):
        headers = [{"key": "X-Organization-Id", "value": "{{organization_id}}"}]
        request = {
            "method": method,
            "url": "{{base_url}}/api/v1" + path,
            "header": headers,
            "auth": {
                "type": "bearer",
                "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}],
            },
        }
        if method == "POST":
            headers += [
                {"key": "Content-Type", "value": "application/json"},
                {"key": "Idempotency-Key", "value": "{{$guid}}"},
            ]
            request["body"] = {
                "mode": "raw",
                "raw": body or "{}",
                "options": {"raw": {"language": "json"}},
            }
        if etag:
            headers.append({"key": "If-Match", "value": "{{" + etag + "}}"})
        items.append(
            {
                "name": name,
                "request": request,
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                "pm.test('Expected status', "
                                f"() => pm.response.to.have.status({status}));"
                            ],
                        },
                    }
                ],
            }
        )

    add(
        "Current routing and payer context",
        "GET",
        "/consignments/{{consignment_id}}/tradetwin-context",
    )
    add(
        "Confirm current loading gate",
        "POST",
        "/consignments/{{consignment_id}}/routing-location-revisions",
        "{{location_json}}",
        "head_etag",
        201,
    )
    add(
        "Owned routing-profile revision",
        "POST",
        "/vehicles/{{vehicle_id}}/routing-profile-revisions",
        "{{profile_json}}",
        "head_etag",
        201,
    )
    add("Retained templates", "GET", "/consignments/{{consignment_id}}/route-templates")
    add(
        "Prepare immutable RFQ",
        "POST",
        "/consignments/{{consignment_id}}/freight-rfqs",
        "{{rfq_json}}",
        "head_etag",
        201,
    )
    add(
        "Publish exact RFQ hash",
        "POST",
        "/freight-rfqs/{{rfq_id}}/publications",
        "{{decision_json}}",
        "head_etag",
    )
    add("Invited operational RFQ", "GET", "/freight-rfqs/{{rfq_id}}")
    add(
        "Carrier prepares fixed offer",
        "POST",
        "/freight-rfqs/{{rfq_id}}/quote-revisions",
        "{{quote_json}}",
        status=201,
    )
    add(
        "Carrier submits exact quote hash",
        "POST",
        "/freight-quote-revisions/{{quote_id}}/submissions",
        "{{decision_json}}",
        "head_etag",
    )
    add(
        "Private external-cost declaration",
        "POST",
        "/consignments/{{consignment_id}}/tradetwin-cost-assumption-revisions",
        "{{assumptions_json}}",
        status=201,
    )
    add(
        "Independent payer declaration review",
        "POST",
        "/tradetwin-cost-assumption-revisions/{{assumption_id}}/reviews",
        "{{decision_json}}",
    )
    add(
        "Run deterministic TradeTwin",
        "POST",
        "/consignments/{{consignment_id}}/tradetwin-runs",
        "{{run_json}}",
        "context_etag",
        202,
    )
    add("Comparison and excluded candidates", "GET", "/tradetwin-runs/{{run_id}}")
    add(
        "Immutable stress comparison",
        "POST",
        "/tradetwin-runs/{{run_id}}/scenario-runs",
        "{{scenario_json}}",
        "context_etag",
        202,
    )
    add(
        "Propose BASE candidate",
        "POST",
        "/consignments/{{consignment_id}}/tradetwin-selections",
        "{{selection_json}}",
        "head_etag",
        201,
    )
    for role in ["payer", "coordinator", "carrier"]:
        add(
            "Exact-hash " + role + " decision",
            "POST",
            "/tradetwin-selections/{{selection_id}}/" + role + "-decisions",
            "{{decision_json}}",
            "head_etag",
        )
    add("Selected operational route", "GET", "/consignments/{{consignment_id}}/route-plan")
    add(
        "Fresh Phase 4 constraints",
        "GET",
        "/consignments/{{consignment_id}}/compliance-constraints",
    )
    add("Decision evidence", "GET", "/tradetwin-runs/{{run_id}}/evidence-manifest")
    add("Commitment evidence", "GET", "/freight-commitments/{{commitment_id}}/evidence-manifest")
    add(
        "Bilateral cancellation proposal",
        "POST",
        "/freight-commitments/{{commitment_id}}/cancellation-proposals",
        "{{cancellation_json}}",
        status=201,
    )
    add(
        "Cancellation decision",
        "POST",
        "/freight-cancellation-proposals/{{cancellation_id}}/decisions",
        "{{decision_json}}",
        "head_etag",
    )
    # Failure templates intentionally use local variables, never private business examples.
    add(
        "Reject stale selection version",
        "POST",
        "/consignments/{{consignment_id}}/tradetwin-selections",
        "{{selection_json}}",
        "stale_etag",
        412,
    )
    add(
        "Reject expired/withdrawn acceptance",
        "POST",
        "/tradetwin-selections/{{selection_id}}/carrier-decisions",
        "{{decision_json}}",
        "head_etag",
        409,
    )
    add(
        "Reject resource conflict",
        "POST",
        "/tradetwin-selections/{{selection_id}}/carrier-decisions",
        "{{decision_json}}",
        "head_etag",
        409,
    )
    add(
        "Route comparison inputs",
        "GET",
        "/consignments/{{consignment_id}}/freight-route-intelligence",
    )
    add(
        "Queue India freight route comparison",
        "POST",
        "/consignments/{{consignment_id}}/freight-route-studies",
        "{{route_study_json}}",
        status=202,
    )
    add("Read current route comparison", "GET", "/freight-route-studies/{{route_study_id}}")
    add(
        "Export permitted route evidence",
        "GET",
        "/freight-route-studies/{{route_study_id}}/evidence-manifest",
    )
    collection = {
        "info": {
            "name": "TradeTwin Phase 5 Freight Planning",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Local templates. Select current role, exact hashes and ETags. "
            "Quotes reserve nothing; commitment does not dispatch or pay.",
        },
        "variable": [{"key": k, "value": v} for k, v in variables.items()],
        "item": items,
    }
    (folder / "freight-planning.collection.json").write_text(
        json.dumps(collection, indent=2) + "\n", encoding="utf-8"
    )
    environment = {
        "name": "TradeTwin Phase 5 Local Template",
        "values": [
            {"key": k, "value": v, "enabled": True, "type": "secret" if k == "token" else "default"}
            for k, v in variables.items()
        ],
        "_postman_variable_scope": "environment",
    }
    (folder / "freight-planning.environment.json").write_text(
        json.dumps(environment, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
