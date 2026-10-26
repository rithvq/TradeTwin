"""Add immutable dashboard explanations; never backfill historical decision reasons."""

from alembic import op
from app.compliance.models_dashboard import TABLES
from app.trades.models import TradeBase

revision = "trade_009"
down_revision = "trade_008"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    names = {model.__tablename__ for model in TABLES}
    TradeBase.metadata.create_all(
        connection, tables=[t for t in TradeBase.metadata.sorted_tables if t.name in names]
    )
    for table in sorted(names):
        if connection.dialect.name == "postgresql":
            op.execute(
                f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION trade_reject_history_mutation()"
            )
        else:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Dispatch explanation is immutable'); END"
                )


def downgrade():
    raise RuntimeError("Forward repair required; retained dispatch explanations must be preserved")
