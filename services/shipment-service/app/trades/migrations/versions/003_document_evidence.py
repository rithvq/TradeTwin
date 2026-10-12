"""Add document evidence without modifying accepted commercial or operational ledgers."""

import sqlalchemy as sa
from alembic import op
from app.document_desk.models import IMMUTABLE_TABLES
from app.trades.models import TradeBase

revision = "trade_003"
down_revision = "trade_002"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    TradeBase.metadata.create_all(
        connection,
        tables=[
            table for table in TradeBase.metadata.sorted_tables if table.name.startswith("doc_")
        ],
    )
    existing = {c["name"] for c in sa.inspect(connection).get_columns("trade_audit_events")}
    for name in ("document_id", "document_version_id"):
        if name not in existing:
            op.add_column("trade_audit_events", sa.Column(name, sa.Uuid(), nullable=True))
            op.create_index(f"ix_trade_audit_{name}", "trade_audit_events", [name])
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
                    "BEGIN SELECT RAISE(ABORT, 'Document evidence is immutable'); END"
                )
    if connection.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER immutable_execution_mode BEFORE UPDATE ON doc_documents "
            "FOR EACH ROW EXECUTE FUNCTION op_protect_execution_mode()"
        )
    else:
        op.execute(
            "CREATE TRIGGER doc_documents_immutable_mode BEFORE UPDATE ON doc_documents "
            "WHEN OLD.execution_mode != NEW.execution_mode "
            "BEGIN SELECT RAISE(ABORT, 'Execution mode is immutable'); END"
        )


def downgrade():
    raise RuntimeError("Document evidence cannot be destructively downgraded")
