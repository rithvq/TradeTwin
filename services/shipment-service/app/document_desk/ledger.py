from app.operations.ledger import view
from app.trades.ledger import audit
from app.trades.models import now

from .models import Document, Version


def record(db, ctx, action, doc, version=None, detail=None):
    from app.trades.models import Trade

    db.flush()
    audit(
        db,
        ctx,
        action,
        version or doc,
        db.get(Trade, doc.trade_id),
        summary=detail or {},
        document=doc,
        document_version=version,
    )


def touch(doc):
    doc.row_version += 1
    doc.updated_at = now()


def match(ctx, doc, code="REVIEW_HEAD_CHANGED"):
    from app.operations.access import fail

    if ctx.if_match != f'"{doc.row_version}"':
        fail(code, "Document head changed. Reload before retrying.")


def result(row, doc=None):
    body = view(row)
    for name in ("object_key", "lease_token", "secret_reference", "public_key_reference"):
        body.pop(name, None)
    if doc:
        body["execution_mode"] = doc.execution_mode
    return body


def root(db, model, ident):
    from app.operations.access import exists

    row = exists(db, model, ident)
    if isinstance(row, Document):
        return row, row
    if isinstance(row, Version):
        return row, db.get(Document, row.document_id)
    version = db.get(Version, row.document_version_id)
    return row, db.get(Document, version.document_id)


def flatten(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"schema_version", "document_line_ref"}:
                continue
            path = f"{prefix}.{key}" if prefix else key
            result.update(flatten(item, path))
    elif isinstance(value, list) and prefix == "lines":
        for line in value:
            result.update(flatten(line, f"lines.{line['document_line_ref']}"))
    elif value is not None:
        result[prefix] = value
    return result


def field_path(path):
    from .schemas import CanonicalDocument, GoodsLine

    parts = path.split(".")
    model = CanonicalDocument
    if parts[0] == "lines" and len(parts) == 3:
        from uuid import UUID

        UUID(parts[1])
        return parts[2] in GoodsLine.model_fields and parts[2] != "document_line_ref"
    for part in parts:
        if part not in model.model_fields:
            return False
        annotation = model.model_fields[part].annotation
        from typing import get_args

        model = next((a for a in get_args(annotation) if hasattr(a, "model_fields")), annotation)
    return True
