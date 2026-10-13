from fastapi.openapi.utils import get_openapi

from .schemas import Address, ErrorResponse, OrganizationFields, TradeFacts


def install_openapi(app):
    def schema():
        if app.openapi_schema:
            return app.openapi_schema
        document = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components = document.setdefault("components", {}).setdefault("schemas", {})
        for model in (Address, OrganizationFields, TradeFacts, ErrorResponse):
            definition = model.model_json_schema(ref_template="#/components/schemas/{model}")
            components.update(definition.pop("$defs", {}))
            components[model.__name__] = definition
        document["components"].setdefault("securitySchemes", {})["ProfileSession"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "Existing OAuth profile session token",
        }
        for path, operations in document["paths"].items():
            if not path.startswith("/api/v1/"):
                continue
            for method, operation in operations.items():
                operation["security"] = [{"ProfileSession": []}]
                for status, description in {
                    401: "Authentication required",
                    403: "Permission denied",
                    404: "Resource not accessible",
                    409: "State or idempotency conflict",
                    412: "Revision mismatch",
                    422: "Field validation failed",
                    503: "Temporary database failure",
                }.items():
                    operation.setdefault("responses", {})[str(status)] = {
                        "description": description,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                            }
                        },
                    }
                operation.setdefault("parameters", []).append(
                    {
                        "name": "X-Organization-Id",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string", "format": "uuid"},
                        "description": (
                            "Required for organisation-scoped resources; "
                            "server validates active membership."
                        ),
                    }
                )
                if method in {"post", "patch", "put"}:
                    body = (
                        operation.get("requestBody", {})
                        .get("content", {})
                        .get("application/json", {})
                        .get("schema", {})
                    )
                    body_name = body.get("$ref", "").rsplit("/", 1)[-1]
                    context_etag = "expected_context_version" in components.get(body_name, {}).get(
                        "properties", {}
                    ) or (
                        path.startswith("/api/v1/compliance-cases/") and path.endswith("/actions")
                    )
                    operation["parameters"].append(
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                        }
                    )
                    if (
                        context_etag
                        or method == "patch"
                        or path.endswith(("/offers", "/amendments"))
                        or (path.startswith("/api/v1/offers/") and path.endswith("/withdrawals"))
                        or path.endswith(
                            (
                                "/preparations",
                                "/cancellations",
                                "/corrections",
                                "/assignments",
                                "/delivery-closures",
                                "/reopenings",
                                "/payment-schedules",
                            )
                        )
                        or method == "put"
                    ):
                        operation["parameters"].append(
                            {
                                "name": "If-Match",
                                "in": "header",
                                "required": method != "put",
                                "schema": {"type": "string"},
                                "description": (
                                    "Current record ETag, including quotes. "
                                    "For carrier-profile PUT, required only when updating "
                                    "an existing profile."
                                ),
                            }
                        )
        from app.operations.contracts import install

        install(document)
        from app.document_desk.contracts import install as install_documents

        install_documents(document)
        app.openapi_schema = document
        return document

    app.openapi = schema
