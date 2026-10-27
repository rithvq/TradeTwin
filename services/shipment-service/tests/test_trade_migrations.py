"""Keep shared ORM metadata from leaking later-phase tables into earlier migrations."""

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.compliance.models import TABLES  # noqa: E402
from app.compliance.models_computation import TABLES as COMPUTATION_TABLES  # noqa: E402
from app.compliance.models_dashboard import TABLES as DASHBOARD_TABLES  # noqa: E402
from app.corridor.models import TABLES as CORRIDOR_TABLES  # noqa: E402
from app.demo_center.models import TABLES as DEMO_TABLES  # noqa: E402
from app.document_desk.models import Document  # noqa: E402
from app.freight.models import TABLES as FREIGHT_TABLES  # noqa: E402
from app.freight_routes.models import TABLES as ROUTE_TABLES  # noqa: E402
from app.operations.models import Assignment  # noqa: E402
from app.product.models import TABLES as PRODUCT_TABLES  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import TradeBase  # noqa: E402


@pytest.fixture()
def migration_engine(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'migrations.db'}")
    schema = f"migration_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def upgrade_to(engine, revision):
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "app/trades/migrations")
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def test_phase_migrations_only_create_their_own_tables(migration_engine):
    # Load all phases before upgrading, as service startup and CI collection do.
    assert Document.__table__.metadata is TradeBase.metadata
    assert Assignment.__table__.metadata is TradeBase.metadata
    assert all(model.__table__.metadata is TradeBase.metadata for model in TABLES)
    assert all(model.__table__.metadata is TradeBase.metadata for model in FREIGHT_TABLES)
    expected = set(TradeBase.metadata.tables)
    commercial = {
        name
        for name in expected
        if (name == "trades" or name.startswith("trade_"))
        and name not in {"trade_compliance_contexts", "trade_workspace_projection_heads"}
    }
    operational = {name for name in expected if name.startswith("op_")}
    documents = {name for name in expected if name.startswith("doc_")}

    upgrade_to(migration_engine, "trade_001")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == commercial

    upgrade_to(migration_engine, "trade_002")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == commercial | operational

    upgrade_to(migration_engine, "trade_003")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == commercial | operational | documents

    upgrade_to(migration_engine, "trade_004")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {
        m.__tablename__
        for m in [
            *FREIGHT_TABLES,
            *CORRIDOR_TABLES,
            *PRODUCT_TABLES,
            *COMPUTATION_TABLES,
            *DASHBOARD_TABLES,
            *ROUTE_TABLES,
            *DEMO_TABLES,
        ]
    }

    upgrade_to(migration_engine, "trade_005")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {
        m.__tablename__
        for m in [
            *CORRIDOR_TABLES,
            *PRODUCT_TABLES,
            *COMPUTATION_TABLES,
            *DASHBOARD_TABLES,
            *ROUTE_TABLES,
            *DEMO_TABLES,
        ]
    }

    upgrade_to(migration_engine, "trade_006")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {
        m.__tablename__
        for m in [
            *PRODUCT_TABLES,
            *COMPUTATION_TABLES,
            *DASHBOARD_TABLES,
            *ROUTE_TABLES,
            *DEMO_TABLES,
        ]
    }

    upgrade_to(migration_engine, "trade_007")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {
        m.__tablename__
        for m in [*COMPUTATION_TABLES, *DASHBOARD_TABLES, *ROUTE_TABLES, *DEMO_TABLES]
    }

    upgrade_to(migration_engine, "trade_008")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {
        m.__tablename__ for m in [*DASHBOARD_TABLES, *ROUTE_TABLES, *DEMO_TABLES]
    }

    upgrade_to(migration_engine, "trade_009")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {m.__tablename__ for m in [*ROUTE_TABLES, *DEMO_TABLES]}

    upgrade_to(migration_engine, "trade_010")
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected - {m.__tablename__ for m in DEMO_TABLES}

    migrate(migration_engine)
    migrate(migration_engine)
    actual = set(inspect(migration_engine).get_table_names()) - {"trade_alembic_version"}
    assert actual == expected
    grants = inspect(migration_engine).get_foreign_keys("doc_access_grants")
    assert any(fk["referred_table"] == "op_transport_assignments" for fk in grants)


def test_fresh_database_upgrades_directly_to_head(migration_engine):
    migrate(migration_engine)
    migrate(migration_engine)
    assert set(TradeBase.metadata.tables).issubset(inspect(migration_engine).get_table_names())
    with migration_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM trade_alembic_version")) == "trade_011"
        )
