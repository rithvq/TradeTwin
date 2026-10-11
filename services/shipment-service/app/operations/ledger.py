from fastapi.encoders import jsonable_encoder
from sqlalchemy.inspection import inspect

from app.trades.access import aware
from app.trades.ledger import audit
from app.trades.models import now

from .quantities import q


def view(row, trade=None, ctx=None):
    from datetime import date, datetime
    from decimal import Decimal

    result = {}
    for column in inspect(type(row)).columns:
        if column.name in {"request_hash", "object_key"}:
            continue
        value = getattr(row, column.name)
        if isinstance(value, Decimal):
            value = q(value)
        elif isinstance(value, datetime):
            value = aware(value).isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        elif column.name.endswith("_minor") and value is not None:
            value = str(value)
        result[column.name] = value
    if hasattr(row, "row_version"):
        result["etag"] = f'"{row.row_version}"'
    if trade:
        result["execution_mode"] = trade.execution_mode
    if ctx:
        result["request_id"] = ctx.request_id
    return jsonable_encoder(result)


def record(db, ctx, action, subject, trade=None, consignment=None, detail=None):
    db.flush()
    audit(db, ctx, action, subject, trade, summary=detail, consignment=consignment)


def touch(row):
    row.row_version += 1
    row.updated_at = now()
