"""Additive compatibility migrations for existing intelligence-service stores."""

from sqlalchemy import String, inspect, text
from sqlalchemy.engine import Engine


def migrate_risk_warning(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    if not inspector.has_table("risk_assessments"):
        return
    warning = next(
        column
        for column in inspector.get_columns("risk_assessments")
        if column["name"] == "warning"
    )
    if isinstance(warning["type"], String) and warning["type"].length is not None:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE risk_assessments ALTER COLUMN warning TYPE TEXT"))
