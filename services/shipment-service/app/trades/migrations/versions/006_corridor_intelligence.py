"""Retain corridor sources, reviewed events, impacts and reported driver responses."""

from alembic import op
from app.corridor.models import IMMUTABLE_TABLES, TABLES
from app.trades.models import TradeBase

revision = "trade_006"
down_revision = "trade_005"
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
                    f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} "
                    f"ON {table} BEGIN SELECT RAISE(ABORT, 'Corridor history is immutable'); END"
                )


def downgrade():
    raise RuntimeError("Corridor evidence cannot be removed by a destructive downgrade")
