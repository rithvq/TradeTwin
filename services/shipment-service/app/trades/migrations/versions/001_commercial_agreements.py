"""Commercial agreement ledger, constraints and immutable history protection."""

from alembic import op
from app.trades.models import TradeBase

revision = "trade_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    TradeBase.metadata.create_all(connection)
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION trade_reject_history_mutation() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'Commercial history is immutable'; END;
            $$ LANGUAGE plpgsql
        """)
        for table in (
            "trade_party_snapshots",
            "trade_revisions",
            "trade_item_revisions",
            "trade_commercial_approvals",
            "trade_audit_events",
        ):
            op.execute(
                f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION trade_reject_history_mutation()"
            )
    elif connection.dialect.name == "sqlite":
        for table in (
            "trade_party_snapshots",
            "trade_revisions",
            "trade_item_revisions",
            "trade_commercial_approvals",
            "trade_audit_events",
        ):
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_immutable_{operation.lower()} "
                    f"BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Commercial history is immutable'); END"
                )


def downgrade():
    raise RuntimeError(
        "Commercial evidence cannot be destructively downgraded; restore a verified backup instead"
    )
