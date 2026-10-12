"""Generate Phase 3 OpenAPI, canonical schema, check pack and Postman examples."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "commercial_contracts", ROOT / "scripts/export-commercial-contracts.py"
)
commercial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commercial)
from app.document_desk.checks import CODES  # noqa: E402
from app.document_desk.schemas import CanonicalDocument  # noqa: E402


def main():
    output = ROOT / "docs/postman"
    output.mkdir(exist_ok=True, parents=True)
    schema = deepcopy(commercial.app.openapi())
    schema["paths"] = {
        path: {
            method: op
            for method, op in operations.items()
            if "Document evidence - Phase 3" in op.get("tags", [])
        }
        for path, operations in schema["paths"].items()
    }
    schema["paths"] = {p: v for p, v in schema["paths"].items() if v}
    variables = {
        "base_url": "http://localhost:8011",
        "token": "",
        "organization_id": "",
        "trade_id": "",
        "document_id": "",
        "version_id": "",
        "clean_attachment_id": "",
        "fact_id": "",
        "run_id": "",
        "job_id": "",
        "document_etag": "",
        "content_hash": "",
        "review_body": "",
        "mapping_body": "",
        "carrier_token": "",
        "carrier_organization_id": "",
    }
    items = []

    def add(name, method, path, body=None, status=200, etag=False, scripts=(), carrier=False):
        headers = [
            {
                "key": "X-Organization-Id",
                "value": "{{carrier_organization_id}}" if carrier else "{{organization_id}}",
            }
        ]
        request = {
            "method": method,
            "url": "{{base_url}}/api/v1" + path,
            "header": headers,
            "auth": {
                "type": "bearer",
                "bearer": [
                    {
                        "key": "token",
                        "type": "string",
                        "value": "{{carrier_token}}" if carrier else "{{token}}",
                    }
                ],
            },
        }
        if body is not None:
            headers.extend(
                [
                    {"key": "Content-Type", "value": "application/json"},
                    {"key": "Idempotency-Key", "value": "{{$guid}}"},
                ]
            )
            request["body"] = {
                "mode": "raw",
                "raw": body if isinstance(body, str) else json.dumps(body, indent=2),
                "options": {"raw": {"language": "json"}},
            }
        if etag:
            headers.append({"key": "If-Match", "value": "{{document_etag}}"})
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
                                f"pm.test('HTTP {status}', "
                                f"() => pm.response.to.have.status({status}));",
                                "const r=pm.response.json(); const v=pm.collectionVariables;",
                                *scripts,
                            ],
                        },
                    }
                ],
            }
        )

    capture = [
        "v.set('document_id',r.id);v.set('version_id',r.current_version_id);v.set('document_etag',r.etag);",
        "v.set('fact_id',r.latest_draft_fact_revision_id||r.effective_fact_revision_id);",
        "pm.test('No dispatch approval',()=>pm.expect(r.status_dimensions.dispatch_readiness)"
        ".to.eql('NOT_ASSESSED'));",
    ]
    add(
        "Register previously uploaded CLEAN invoice",
        "POST",
        "/trades/{{trade_id}}/documents",
        {
            "trade_id": "{{trade_id}}",
            "document_type": "TAX_INVOICE",
            "label": "Invoice",
            "primary_attachment_id": "{{clean_attachment_id}}",
            "visibility": "OWNER_ONLY",
        },
        201,
        scripts=capture,
    )
    add(
        "Queue actual native extraction",
        "POST",
        "/document-versions/{{version_id}}/processing-jobs",
        {"stage": "EXTRACT", "strategy": "NATIVE_TEXT"},
        202,
        scripts=["v.set('job_id',r.job_id);"],
    )
    add(
        "Poll job until terminal; retain attempts",
        "GET",
        "/document-processing-jobs/{{job_id}}",
        scripts=[
            "pm.test('No worker credential',()=>pm.expect(JSON.stringify(r))"
            ".not.to.include('lease_token'));",
            "if(r.extraction_run_ids.length)v.set('run_id',r.extraction_run_ids.at(-1));",
        ],
    )
    add(
        "Reload document head after job finishes",
        "GET",
        "/documents/{{document_id}}",
        scripts=capture,
    )
    add("Source-linked observations", "GET", "/document-extraction-runs/{{run_id}}/observations")
    add(
        "Load proposed fact; reviewer must explicitly prepare review_body",
        "GET",
        "/document-fact-revisions/{{fact_id}}",
        scripts=[
            "v.set('content_hash',r.content_hash);",
            "pm.test('No invented confidence',()=>pm.expect(r.canonical_document_json)"
            ".to.be.an('object'));",
        ],
    )
    add(
        "Save human review with explicit provenance",
        "POST",
        "/document-versions/{{version_id}}/fact-revisions",
        "{{review_body}}",
        201,
        True,
        [
            "v.set('fact_id',r.id);v.set('content_hash',r.content_hash);v.set('document_etag',r.etag);"
        ],
    )
    add(
        "Submit exact reviewed snapshot",
        "POST",
        "/document-fact-revisions/{{fact_id}}/submissions",
        {"content_hash": "{{content_hash}}"},
        200,
        True,
    )
    add("Reload exact head", "GET", "/documents/{{document_id}}", scripts=capture)
    add(
        "Human-confirmed 40/60 mappings (prepare mapping_body)",
        "POST",
        "/documents/{{document_id}}/mapping-revisions",
        "{{mapping_body}}",
        201,
        True,
    )
    add(
        "Queue reviewed data checks",
        "POST",
        "/document-versions/{{version_id}}/assessment-runs",
        {"fact_revision_id": "{{fact_id}}", "scope": "TRADE"},
        202,
    )
    add(
        "Request unavailable authority check honestly",
        "POST",
        "/document-versions/{{version_id}}/verification-checks",
        {
            "fact_revision_id": "{{fact_id}}",
            "check_type": "GSTIN_AUTHORITY_LOOKUP",
            "target_field_path": "parties.supplier.gstin",
        },
        202,
    )
    add(
        "Export permission-filtered provenance",
        "GET",
        "/document-versions/{{version_id}}/evidence-manifest",
        scripts=[
            "pm.test('No storage secrets',()=>pm.expect(JSON.stringify(r))"
            ".not.to.include('object_key'));",
            "pm.test('Dispatch not assessed',()=>pm.expect(r.dispatch_readiness)"
            ".to.eql('NOT_ASSESSED'));",
        ],
    )
    add(
        "Failure: forged universal verification flag",
        "POST",
        "/trades/{{trade_id}}/documents",
        {
            "trade_id": "{{trade_id}}",
            "document_type": "TAX_INVOICE",
            "label": "Rejected",
            "primary_attachment_id": "{{clean_attachment_id}}",
            "verified": True,
        },
        422,
    )
    add(
        "Failure: wrong snapshot hash",
        "POST",
        "/document-fact-revisions/{{fact_id}}/submissions",
        {"content_hash": "0" * 64},
        409,
        True,
    )
    add(
        "Failure: carrier cannot fetch invoice OCR",
        "GET",
        "/document-extraction-runs/{{run_id}}/observations",
        status=404,
        carrier=True,
    )
    collection = {
        "info": {
            "name": "TradeTwin Phase 3 Document Desk",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Explicit reviewer inputs required. Upload/finalise CLEAN files "
            "with the existing Phase 2 collection. Poll jobs before using extracted heads; "
            "no provider credentials bundled.",
        },
        "variable": [{"key": k, "value": v} for k, v in variables.items()],
        "item": items,
    }
    artifacts = {
        "document-desk.openapi.json": schema,
        "document-desk.postman_collection.json": collection,
        "PH3_CANONICAL_V1.schema.json": CanonicalDocument.model_json_schema(),
        "PH3_DOCUMENT_DATA_CHECKS_V1.json": {
            "id": "PH3_DOCUMENT_DATA_CHECKS_V1",
            "version": "1",
            "status": "PUBLISHED",
            "kind": "DATA_RECONCILIATION_ONLY",
            "missing_input_outcome": "UNKNOWN",
            "unsupported_profile_outcome": "NOT_EVALUATED",
            "draft_stage": "PROVISIONAL",
            "dispatch_readiness": "NOT_ASSESSED",
            "checks": [{"code": code, "version": "1"} for code in CODES],
        },
    }
    for name, content in artifacts.items():
        (output / name).write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(items)} document requests, canonical schema, check pack and OpenAPI")


if __name__ == "__main__":
    main()
