"""Add derived product views and internal assurance without changing business ledgers."""

from alembic import op
from app.product.models import IMMUTABLE_TABLES, TABLES
from app.trades.models import TradeBase

revision = "trade_007"
down_revision = "trade_006"
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
                    f"ON {table} BEGIN SELECT RAISE(ABORT, 'Product evidence is immutable'); END"
                )
    for table in ("decision_replay_requests", "readiness_runs"):
        if connection.dialect.name == "postgresql":
            op.execute(
                f"CREATE TRIGGER immutable_completed_result BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION freight_preserve_run()"
            )
        else:
            op.execute(
                f"CREATE TRIGGER {table}_completed BEFORE UPDATE ON {table} "
                "WHEN OLD.job_state IN ('COMPLETED','FAILED','CANCELLED') "
                "BEGIN SELECT RAISE(ABORT, 'Completed evidence is immutable'); END"
            )
            op.execute(
                f"CREATE TRIGGER {table}_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'Evidence history is immutable'); END"
            )


def downgrade():
    raise RuntimeError("Forward repair required; retained product evidence must not be dropped")
