"""Trusted UTC time with a scoped injectable clock for deterministic tests, never an API input."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from sqlalchemy import text

_test_clock = ContextVar("compliance_test_clock", default=None)


def instant(db=None):
    clock = _test_clock.get()
    if clock is not None:
        return clock().astimezone(UTC)
    if db is not None and db.get_bind().dialect.name == "postgresql":
        return db.scalar(text("SELECT clock_timestamp()"))
    return datetime.now(UTC)


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@contextmanager
def use_test_clock(clock):
    token = _test_clock.set(clock)
    try:
        yield
    finally:
        _test_clock.reset(token)
