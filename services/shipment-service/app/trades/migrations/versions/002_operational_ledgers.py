"""Add operational ledgers without replacing commercial records."""

import sqlalchemy as sa
from alembic import op
from app.operations.models import IMMUTABLE_TABLES
from app.trades.models import TradeBase

revision = "trade_002"
down_revision = "trade_001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for table, columns in {
        "trades": [
            sa.Column("execution_mode", sa.String(20), nullable=False, server_default="PRODUCTION"),
            sa.Column("active_payment_schedule_id", sa.Uuid(), nullable=True),
            sa.Column(
                "payment_schedule_review_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        ],
        "trade_audit_events": [
            sa.Column("consignment_id", sa.Uuid(), nullable=True),
            sa.Column("execution_mode", sa.String(20), nullable=False, server_default="PRODUCTION"),
        ],
    }.items():
        existing = {item["name"] for item in sa.inspect(connection).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    TradeBase.metadata.create_all(
        connection,
        tables=[
            table for table in TradeBase.metadata.sorted_tables if table.name.startswith("op_")
        ],
    )
    schedule_columns = [
        c.name
        for c in TradeBase.metadata.tables["op_payment_schedules"].columns
        if c.name != "status"
    ]
    if connection.dialect.name == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION trade_reject_history_mutation()"
            )
        op.execute("""CREATE FUNCTION op_protect_execution_mode() RETURNS trigger AS $$
            BEGIN IF OLD.execution_mode IS DISTINCT FROM NEW.execution_mode THEN
            RAISE EXCEPTION 'Execution mode is immutable'; END IF; RETURN NEW; END;
            $$ LANGUAGE plpgsql""")
        for table in ("trades", "op_consignments"):
            op.execute(
                f"CREATE TRIGGER immutable_execution_mode BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION op_protect_execution_mode()"
            )
        columns = ", ".join(schedule_columns)
        op.execute(
            f"CREATE TRIGGER immutable_schedule BEFORE UPDATE OF {columns} OR DELETE "
            "ON op_payment_schedules FOR EACH ROW "
            "EXECUTE FUNCTION trade_reject_history_mutation()"
        )
    else:
        for table in IMMUTABLE_TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Operational history is immutable'); END"
                )
        for table in ("trades", "op_consignments"):
            op.execute(
                f"CREATE TRIGGER {table}_immutable_mode BEFORE UPDATE ON {table} "
                "WHEN OLD.execution_mode != NEW.execution_mode "
                "BEGIN SELECT RAISE(ABORT, 'Execution mode is immutable'); END"
            )
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in schedule_columns)
        op.execute(
            "CREATE TRIGGER immutable_schedule BEFORE UPDATE ON op_payment_schedules "
            f"WHEN {changed} BEGIN SELECT RAISE(ABORT, 'Schedule content is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER immutable_schedule_delete BEFORE DELETE ON op_payment_schedules "
            "BEGIN SELECT RAISE(ABORT, 'Schedule content is immutable'); END"
        )


def downgrade():
    raise RuntimeError("Operational evidence cannot be destructively downgraded")
