"""Document mutable-head preconditions without weakening commercial contracts."""


def install(document):
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            if "Freight planning - Phase 5" not in operation.get("tags", []):
                continue
            if method != "post":
                continue
            mutable = path.endswith(
                (
                    "routing-location-revisions",
                    "routing-profile-revisions",
                    "freight-rfqs",
                    "tradetwin-selections",
                    "payer-decisions",
                    "coordinator-decisions",
                    "carrier-decisions",
                    "submissions",
                    "withdrawals",
                    "closures",
                    "invitations",
                    "decisions",
                )
            )
            mutable = mutable or (
                path.startswith("/api/v1/freight-rfqs/") and path.endswith("publications")
            )
            if mutable:
                existing = next(
                    (p for p in operation["parameters"] if p["name"] == "If-Match"), None
                )
                if existing:
                    existing["required"] = True
                else:
                    operation["parameters"].append(
                        {
                            "name": "If-Match",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Current record head ETag.",
                        }
                    )
