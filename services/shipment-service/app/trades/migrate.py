from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.compliance import models_computation as computation_models  # noqa: F401
from app.corridor import models as corridor_models  # noqa: F401
from app.demo_center import models as demo_models  # noqa: F401
from app.freight_routes import models as freight_route_models  # noqa: F401
from app.product import models as product_models  # noqa: F401


def migrate(engine):
    """Executable, versioned additive migration, serialized across service replicas."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(884930)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
