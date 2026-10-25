"""Consignment-local rule calculations, absence witnesses and scoped transactional epochs."""

from alembic import op
from app.compliance.epoch_triggers import install
from app.compliance.models_computation import IMMUTABLE_TABLES, TABLES
from app.trades.models import TradeBase

revision = "trade_008"
down_revision = "trade_007"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    names = {model.__tablename__ for model in TABLES}
    TradeBase.metadata.create_all(
        connection, tables=[t for t in TradeBase.metadata.sorted_tables if t.name in names]
    )
    for table in IMMUTABLE_TABLES:
        if connection.dialect.name == "postgresql":
            op.execute(
                f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION trade_reject_history_mutation()"
            )
        else:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Calculation history is immutable'); END"
                )
    install(connection)


def downgrade():
    raise RuntimeError("Forward repair required; historical calculation evidence must be retained")
