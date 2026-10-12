"""Published wire schemas and concurrency headers, derived from the evidence models."""

from sqlalchemy import DateTime, Numeric, Uuid, inspect

from app.operations.contracts import array, object_schema, ref

from . import models
from .schemas import CanonicalDocument


def install(document):
    components = document["components"]["schemas"]
    canonical = CanonicalDocument.model_json_schema(ref_template="#/components/schemas/{model}")
    components.update(canonical.pop("$defs", {}))
    components["CanonicalDocument"] = canonical
    for name in (
        "Document",
        "Version",
        "FactRevision",
        "FieldDecision",
        "Observation",
        "Job",
        "Assessment",
        "Finding",
        "MappingRevision",
        "LineMapping",
        "VerificationCheck",
        "VerificationResult",
        "ManualAttestation",
        "AccessGrant",
        "Extraction",
        "Asset",
    ):
        properties = {}
        for column in inspect(getattr(models, name)).columns:
            if column.name in {"object_key", "lease_token", "request_json"}:
                continue
            kind = column.type
            value = (
                {"type": "string", "format": "uuid"}
                if isinstance(kind, Uuid)
                else {"type": "string", "format": "date-time"}
                if isinstance(kind, DateTime)
                else {"type": "string", "description": "Exact decimal, never float"}
                if isinstance(kind, Numeric)
                else {"description": f"Server field: {column.name}"}
            )
            properties[column.name] = (
                {"anyOf": [value, {"type": "null"}]} if column.nullable else value
            )
        properties.update(
            execution_mode={"enum": ["SIMULATION", "PRODUCTION"]}, etag={"type": "string"}
        )
        # Projections add permission-filtered metadata to the persisted wire fields.
        definition = object_schema(properties)
        definition["additionalProperties"] = True
        components[f"DocumentDesk{name}"] = definition
    components["DocumentDeskFactRevision"]["properties"].update(
        canonical_document_json=ref("CanonicalDocument"),
        field_decisions=array("DocumentDeskFieldDecision"),
    )
    components["DocumentDeskDocument"]["properties"].update(
        current_version=ref("DocumentDeskVersion"),
        versions=array("DocumentDeskVersion"),
        status_dimensions={"type": "object", "additionalProperties": {"type": ["string", "null"]}},
        allowed_actions={"type": "array", "items": {"type": "string"}},
    )
    components["DocumentDeskVersion"]["properties"].update(
        document=ref("DocumentDeskDocument"), assets=array("DocumentDeskAsset")
    )
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if "Document evidence - Phase 3" not in operation.get("tags", []):
                continue
            if method == "post" and path.endswith(
                (
                    "/versions",
                    "/fact-revisions",
                    "/submissions",
                    "/mapping-revisions",
                    "/archives",
                    "/relationships",
                )
            ):
                operation.setdefault("parameters", []).append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Exact current document ETag; "
                        "historical evidence is immutable.",
                    }
                )
            output = None
            if method == "get":
                output = (
                    "Document"
                    if path.startswith("/api/v1/documents/") and path.count("/") == 4
                    else "Version"
                    if path.startswith("/api/v1/document-versions/") and path.count("/") == 4
                    else "FactRevision"
                    if path.startswith("/api/v1/document-fact-revisions/")
                    else "Job"
                    if path.startswith("/api/v1/document-processing-jobs/")
                    else "Assessment"
                    if path.startswith("/api/v1/document-assessment-runs/")
                    else None
                )
            if output:
                operation["responses"]["200"]["content"] = {
                    "application/json": {"schema": ref(f"DocumentDesk{output}")}
                }
