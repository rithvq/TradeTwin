from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.corridor import models as corridor_models  # noqa: F401


def migrate(engine):
    """Executable, versioned additive migration, serialized across service replicas."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(884930)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
