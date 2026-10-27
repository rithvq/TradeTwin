"""Profile-owned integrated simulation sessions; retain completed command receipts."""

from alembic import op
from app.demo_center.models import TABLES
from app.trades.models import TradeBase

revision = "trade_011"
down_revision = "trade_010"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    names = {model.__tablename__ for model in TABLES}
    TradeBase.metadata.create_all(
        connection, tables=[t for t in TradeBase.metadata.sorted_tables if t.name in names]
    )
    if connection.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION preserve_demo_command() RETURNS trigger AS $$
            BEGIN IF TG_OP = 'DELETE' OR OLD.status IN ('COMPLETED','FAILED')
            THEN RAISE EXCEPTION 'Demo command receipts are immutable'; END IF;
            RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute(
            "CREATE TRIGGER preserve_demo_command BEFORE UPDATE OR DELETE ON demo_app_commands "
            "FOR EACH ROW EXECUTE FUNCTION preserve_demo_command()"
        )
    else:
        op.execute(
            "CREATE TRIGGER preserve_demo_command_update BEFORE UPDATE ON demo_app_commands "
            "WHEN OLD.status IN ('COMPLETED','FAILED') "
            "BEGIN SELECT RAISE(ABORT, 'Demo command receipts are immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER preserve_demo_command_delete BEFORE DELETE ON demo_app_commands "
            "BEGIN SELECT RAISE(ABORT, 'Demo command receipts are immutable'); END"
        )


def downgrade():
    raise RuntimeError("Forward repair required; demo evidence must be retained")
