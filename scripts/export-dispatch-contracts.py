"""Generate versioned Phase 4 schemas, OpenAPI and credential-free local Postman tools."""

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
from app.compliance.schemas_dispatch import AuthorizationInput, PacketPrepare  # noqa: E402
from app.compliance.schemas_facts import (  # noqa: E402
    EvidenceBindings,
    Facts,
    LoadingManifest,
    RecipientInput,  # noqa: E402
    TransportInput,
    TurnoverInput,
)
from app.compliance.schemas_rules import PackInput, SourceInput  # noqa: E402
from app.compliance.schemas_views import (  # noqa: E402
    ConstraintView,
    EvidenceManifestView,
    ReadinessView,
)
from app.document_desk.schemas import CanonicalDocument  # noqa: E402


def main():
    folder = ROOT / "docs/postman"
    folder.mkdir(parents=True, exist_ok=True)
    schema = deepcopy(commercial.app.openapi())
    schema["paths"] = {
        path: {
            method: operation
            for method, operation in operations.items()
            if "Compliance and guarded dispatch - Phase 4" in operation.get("tags", [])
            or path == "/api/v1/consignments/{ident}/events"
        }
        for path, operations in schema["paths"].items()
    }
    schema["paths"] = {p: v for p, v in schema["paths"].items() if v}
    schema = prune(schema)
    (folder / "guarded-dispatch.openapi.json").write_text(json.dumps(schema, indent=2) + "\n")
    for name, model in {
        "COMPLIANCE_FACTS_V1": Facts,
        "PAN_TURNOVER_DECLARATION_V1": TurnoverInput,
        "LOADING_MANIFEST_V1": LoadingManifest,
        "TRANSPORT_EVIDENCE_V1": TransportInput,
        "CONSIGNMENT_EVIDENCE_BINDINGS_V1": EvidenceBindings,
        "PH4_TYPED_RULES_V1": PackInput,
        "REGULATION_SOURCE_V1": SourceInput,
        "DISPATCH_PACKET_V1": PacketPrepare,
        "DISPATCH_AUTHORISATION_V1": AuthorizationInput,
        "PH4_CANONICAL_V2": CanonicalDocument,
        "RECIPIENT_CONFIRMATION_V1": RecipientInput,
        "COMPLIANCE_CONSTRAINTS_V1": ConstraintView,
        "PH4_EVIDENCE_MANIFEST_V1": EvidenceManifestView,
        "PH4_READINESS_V1": ReadinessView,
    }.items():
        value = model.model_json_schema(mode="serialization", by_alias=True)
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (folder / f"{name}.schema.json").write_text(json.dumps(value, indent=2) + "\n")
    variables = {
        "base_url": "http://localhost:8011",
        "context_version": "0",
        "consignment_id": "",
        "trade_id": "",
        "context_etag": "",
        "fact_id": "",
        "evaluation_id": "",
        "evaluation_hash": "",
        "approval_id": "",
        "packet_id": "",
        "packet_hash": "",
        "assignment_id": "",
        "acknowledgment_id": "",
        "authorisation_id": "",
        "loading_manifest_revision_id": "",
        "turnover_id": "",
        "transport_id": "",
        "facts_json": "{}",
        "turnover_json": "{}",
        "manifest_json": "{}",
        "bindings_json": "{}",
        "transport_json": "{}",
        "representations_json": "[]",
        "event_json": "{}",
        "source_json": "{}",
        "pack_json": "{}",
        "pack_id": "",
        "pack_hash": "",
        "passed_test_run_id": "",
        "review_approval_event_id": "",
        "action": "PICKUP_CONFIRMED",
    }
    for role in ("preparer", "reviewer", "driver", "dispatcher", "author", "publisher"):
        variables[role + "_token"] = ""
        variables[role + "_org"] = ""
    groups = {
        "Read-only smoke": [],
        "Preparation": [],
        "Release chain": [],
        "Governance": [],
        "Failure checks": [],
    }

    def add(
        group, name, method, path, body=None, role="preparer", status=200, capture=(), etag=False
    ):
        headers = [{"key": "X-Organization-Id", "value": "{{" + role + "_org}}"}]
        request = {
            "method": method,
            "url": "{{base_url}}/api/v1" + path,
            "header": headers,
            "auth": {
                "type": "bearer",
                "bearer": [{"key": "token", "type": "string", "value": "{{" + role + "_token}}"}],
            },
        }
        if body:
            headers.extend(
                [
                    {"key": "Content-Type", "value": "application/json"},
                    {"key": "Idempotency-Key", "value": "{{$guid}}"},
                ]
            )
            request["body"] = {"mode": "raw", "raw": body, "options": {"raw": {"language": "json"}}}
        if etag:
            headers.append({"key": "If-Match", "value": "{{context_etag}}"})
        groups[group].append(
            {
                "name": name,
                "request": request,
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                f"pm.test('HTTP {status}',"
                                f"()=>pm.response.to.have.status({status}));",
                                "const r=pm.response.json();const v=pm.collectionVariables;",
                                *capture,
                            ],
                        },
                    }
                ],
            }
        )

    base = "/consignments/{{consignment_id}}"
    add(
        "Read-only smoke",
        "Role-filtered current context",
        "GET",
        base + "/compliance-context",
        capture=["v.set('context_version',r.context_version);v.set('context_etag',r.etag);"],
    )
    add(
        "Read-only smoke",
        "Live readiness, never cached READY",
        "GET",
        base + "/dispatch-readiness?action={{action}}",
    )
    add(
        "Read-only smoke",
        "Constraint snapshot without private history",
        "GET",
        base + "/compliance-constraints?action={{action}}",
        capture=[
            "pm.test('No private PAN history',()=>pm.expect(JSON.stringify(r))"
            ".not.to.include('pan_aggregate_turnover_minor'));"
        ],
    )
    add("Read-only smoke", "Supported scope registry", "GET", "/regulations/supported-scope")
    add(
        "Preparation",
        "Prepare and submit exact facts",
        "POST",
        base + "/compliance-fact-revisions",
        '{"expected_context_version":{{context_version}},"facts":{{facts_json}},"submit_for_review":true}',
        status=201,
        etag=True,
        capture=["v.set('fact_id',r.id);"],
    )
    add(
        "Preparation",
        "Independently review facts",
        "POST",
        "/compliance-fact-revisions/{{fact_id}}/reviews",
        '{"decision":"APPROVE_DECLARATION","reason":"Independent declaration review"}',
        role="reviewer",
        status=201,
    )
    add(
        "Preparation",
        "Private seller declaration",
        "POST",
        "/organisations/{{preparer_org}}/pan-turnover-declarations",
        "{{turnover_json}}",
        status=201,
        capture=["v.set('turnover_id',r.id);"],
    )
    add(
        "Preparation",
        "Independent private turnover review",
        "POST",
        "/pan-turnover-declarations/{{turnover_id}}/reviews",
        '{"decision":"APPROVE_DECLARATION","reason":"Independent private record review"}',
        role="reviewer",
        status=201,
    )
    add(
        "Preparation",
        "Pin loading manifest",
        "POST",
        base + "/loading-manifest-revisions",
        '{"expected_context_version":{{context_version}},"manifest":{{manifest_json}}}',
        status=201,
        etag=True,
        capture=["v.set('loading_manifest_revision_id',r.id);"],
    )
    add(
        "Preparation",
        "Transport evidence",
        "POST",
        base + "/transport-evidence-revisions",
        "{{transport_json}}",
        status=201,
        capture=["v.set('transport_id',r.id);"],
    )
    add(
        "Preparation",
        "Independent transport review",
        "POST",
        "/transport-evidence-revisions/{{transport_id}}/reviews",
        '{"decision":"APPROVE_DECLARATION","reason":"Independent source/assignment review"}',
        role="reviewer",
        status=201,
    )
    add(
        "Preparation",
        "Bind exact reviewed evidence",
        "POST",
        base + "/compliance-evidence-binding-revisions",
        '{"expected_context_version":{{context_version}},"bindings":{{bindings_json}}}',
        status=201,
        etag=True,
    )
    add(
        "Release chain",
        "Queue action-specific evaluation",
        "POST",
        base + "/compliance-evaluations",
        '{"action":"{{action}}","expected_context_version":{{context_version}}}',
        status=202,
        etag=True,
        capture=["v.set('evaluation_id',r.evaluation_id);"],
    )
    add(
        "Release chain",
        "Poll immutable evaluation until completed",
        "GET",
        "/compliance-evaluations/{{evaluation_id}}",
        capture=["if(r.evaluation_hash)v.set('evaluation_hash',r.evaluation_hash);"],
    )
    add(
        "Release chain",
        "Independent release decision",
        "POST",
        "/compliance-evaluations/{{evaluation_id}}/review-decisions",
        '{"decision":"APPROVE_RELEASE","evaluation_hash":"{{evaluation_hash}}",'
        '"acknowledged_warning_action_ids":[],"reason":"Independent exact evaluation review"}',
        role="reviewer",
        status=201,
        capture=["v.set('approval_id',r.id);"],
    )
    add(
        "Release chain",
        "Prepare assignment-bound packet",
        "POST",
        base + "/dispatch-packets",
        '{"action":"{{action}}","evaluation_id":"{{evaluation_id}}","evaluation_hash":"{{evaluation_hash}}","approval_id":"{{approval_id}}","selected_representations":{{representations_json}}}',
        role="dispatcher",
        status=201,
        capture=[
            "v.set('packet_id',r.id);v.set('packet_hash',r.packet_hash);v.set('assignment_id',r.assignment_id);"
        ],
    )
    add(
        "Release chain",
        "Assigned driver possession ACK",
        "POST",
        "/dispatch-packets/{{packet_id}}/acknowledgments",
        '{"packet_hash":"{{packet_hash}}","assignment_id":"{{assignment_id}}","possession_confirmed":true,"carry_methods":["PAPER_COPY","EWB_NUMBER_AVAILABLE"]}',
        role="driver",
        status=201,
        capture=["v.set('acknowledgment_id',r.id);"],
    )
    add(
        "Release chain",
        "Issue guarded platform authorisation",
        "POST",
        base + "/dispatch-authorizations",
        '{"action":"{{action}}","evaluation_id":"{{evaluation_id}}","evaluation_hash":"{{evaluation_hash}}","approval_id":"{{approval_id}}","packet_id":"{{packet_id}}","packet_hash":"{{packet_hash}}","acknowledgment_id":"{{acknowledgment_id}}","expected_context_version":{{context_version}}}',
        role="dispatcher",
        status=201,
        etag=True,
        capture=["v.set('authorisation_id',r.authorisation_id);"],
    )
    add(
        "Release chain",
        "Execute existing atomic movement command",
        "POST",
        base + "/events",
        "{{event_json}}",
        role="driver",
        status=201,
    )
    add(
        "Release chain",
        "Evidence-grounded authorisation export",
        "GET",
        "/dispatch-authorizations/{{authorisation_id}}/evidence-manifest",
    )
    add(
        "Governance",
        "Register exact clean official source",
        "POST",
        "/regulations/sources",
        "{{source_json}}",
        role="author",
        status=201,
    )
    add(
        "Governance",
        "Create immutable unpublished pack",
        "POST",
        "/regulations/rule-pack-revisions",
        "{{pack_json}}",
        role="author",
        status=201,
        capture=["v.set('pack_id',r.id);v.set('pack_hash',r.content_hash);"],
    )
    add(
        "Governance",
        "Run immutable registered tests",
        "POST",
        "/regulations/rule-pack-revisions/{{pack_id}}/test-runs",
        '{"pack_hash":"{{pack_hash}}","test_suite_id":"PH4_REQUIRED_BOUNDARIES_V1"}',
        role="author",
        status=201,
        capture=["if(r.status==='PASSED')v.set('passed_test_run_id',r.id);"],
    )
    add(
        "Governance",
        "Independently approve tested hash",
        "POST",
        "/regulations/rule-pack-revisions/{{pack_id}}/review-approvals",
        '{"pack_hash":"{{pack_hash}}","passed_test_run_id":"{{passed_test_run_id}}",'
        '"reason":"Independent source and coverage review"}',
        role="publisher",
        status=201,
        capture=["v.set('review_approval_event_id',r.id);"],
    )
    add(
        "Governance",
        "Publish reviewed version",
        "POST",
        "/regulations/rule-pack-revisions/{{pack_id}}/publications",
        '{"pack_hash":"{{pack_hash}}","review_approval_event_id":"{{review_approval_event_id}}"}',
        role="publisher",
        status=201,
    )
    add(
        "Failure checks",
        "Preparer self-review is denied",
        "POST",
        "/compliance-evaluations/{{evaluation_id}}/review-decisions",
        '{"decision":"APPROVE_RELEASE","evaluation_hash":"{{evaluation_hash}}",'
        '"reason":"Expect independent reviewer requirement"}',
        status=403,
    )
    add(
        "Failure checks",
        "Stale context is rejected",
        "POST",
        base + "/compliance-evaluations",
        '{"action":"{{action}}","expected_context_version":999999999}',
        status=412,
        etag=True,
    )
    add(
        "Failure checks",
        "Read expired/stale/consumed token state",
        "GET",
        "/dispatch-authorizations/{{authorisation_id}}",
    )
    collection = {
        "info": {
            "name": "TradeTwin Guarded Dispatch Phase 4",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Local only. Use distinct authenticated actors. "
            "Fill JSON bodies from named schemas and reviewed current records. "
            "Reload context after every factual write. Poll 202 jobs before review. "
            "Preserve request keys manually for retries. "
            "Never share populated environments, credentials or private records.",
        },
        "variable": [{"key": k, "value": v} for k, v in variables.items()],
        "item": [{"name": name, "item": items} for name, items in groups.items()],
    }
    (folder / "guarded-dispatch.postman_collection.json").write_text(
        json.dumps(collection, indent=2) + "\n"
    )
    environment = {
        "name": "TradeTwin Phase 4 LOCAL ONLY",
        "values": [
            {
                "key": k,
                "value": v,
                "enabled": True,
                "type": "secret" if k.endswith("_token") else "default",
            }
            for k, v in variables.items()
        ],
        "_postman_variable_scope": "environment",
    }
    (folder / "guarded-dispatch.local.postman_environment.json").write_text(
        json.dumps(environment, indent=2) + "\n"
    )
    print(
        f"Exported {len(schema['paths'])} paths, 14 schemas and a local, credential-free collection"
    )


if __name__ == "__main__":
    main()
