from sqlalchemy import inspect

from app.operations.access import fail
from app.trades.ledger import audit
from app.trades.models import Trade

from .clock import aware, instant


def record(db, ctx, code, row, trade_id=None, summary=None):
    db.flush()
    ident = trade_id or getattr(row, "trade_id", None)
    trade = db.get(Trade, ident) if ident else None
    audit(db, ctx, code, row, trade, summary=summary or {})


def view(row):
    data = {}
    for column in inspect(type(row)).columns:
        value = getattr(row, column.name)
        data[column.name] = (
            aware(value).isoformat()
            if column.type.python_type.__name__ == "datetime" and value
            else value
        )
    return data


def check_context(ctx, version, expected):
    if expected != version or ctx.if_match != f'"{version}"':
        fail(
            "EVALUATION_STALE",
            "Compliance context changed; reload its current version and ETag.",
            status=412,
            details={
                "current_context_version": version,
                "permitted_next_actions": ["RELOAD_CONTEXT"],
            },
        )


def independent(ctx, prepared_by):
    if ctx.user.id == prepared_by:
        fail(
            "SELF_REVIEW_NOT_ALLOWED",
            "A different explicitly authorised user must review this exact record.",
            status=403,
        )


def valid_window(db, start, end):
    now = instant(db)
    return (start is None or aware(start) <= now) and end is not None and now < aware(end)
