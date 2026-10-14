"""Document the same ETag requirements enforced by corridor mutation commands."""


def install(document):
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            if method != "post" or "Corridor intelligence - Phase 6" not in operation.get(
                "tags", []
            ):
                continue
            if not path.endswith(
                (
                    "/status",
                    "/event-revisions",
                    "/corridor-reassessments",
                    "/recovery-cases",
                    "/driver-responses",
                )
            ):
                continue
            if any(p.get("name") == "If-Match" for p in operation.get("parameters", [])):
                continue
            operation.setdefault("parameters", []).append(
                {
                    "name": "If-Match",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": (
                        "Current compliance-context ETag for reassessments; "
                        "current mutable-head ETag for other commands."
                    ),
                }
            )
