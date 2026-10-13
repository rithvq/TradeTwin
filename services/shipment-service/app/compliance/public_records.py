"""Permission-filtered projections never grant access to a referenced original."""

from copy import deepcopy

from app.document_desk import access
from app.trades.errors import TradeError

from .ledger import view


def readable_version(db, ctx, ident):
    try:
        access.version(db, ctx, ident)
        return True
    except TradeError:
        return False


def requirement(db, ctx, row):
    body = view(row)
    observed = deepcopy(body["observed_json"])
    observed["correction_links"] = [
        link
        for link in observed.get("correction_links", [])
        if readable_version(db, ctx, link["document_version_id"])
    ]
    body["observed_json"] = observed
    body["evidence_refs_json"] = [
        reference
        for reference in body["evidence_refs_json"]
        if not reference.get("document_version_id")
        or readable_version(db, ctx, reference["document_version_id"])
    ]
    return body


def input_references(snapshot):
    refs = []
    for kind in ("fact", "manifest", "binding"):
        if snapshot.get(kind):
            refs.append(
                {"kind": kind, "id": snapshot[kind]["id"], "content_hash": snapshot[kind]["hash"]}
            )
    for document in snapshot.get("documents", []):
        refs.append(
            {
                "kind": "reviewed_document",
                **document["reference"],
                "source_manifest_hash": document["source_hash"],
                "fact_hash": document["fact_hash"],
            }
        )
    for observed in snapshot.get("verification_results", []):
        refs.append(
            {
                "kind": "verification",
                "id": observed["id"],
                "content_hash": observed["hash"],
                "selected": observed["selected"],
            }
        )
    for record in snapshot.get("transport", []):
        refs.append({"kind": "transport", "id": record["id"], "content_hash": record["hash"]})
    return refs
