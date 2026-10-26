"""Retain route comparisons without changing commercial commitments or release authority."""

from alembic import op
from app.freight_routes.models import TABLES
from app.trades.models import TradeBase

revision = "trade_010"
down_revision = "trade_009"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    names = {model.__tablename__ for model in TABLES}
    TradeBase.metadata.create_all(
        connection, tables=[t for t in TradeBase.metadata.sorted_tables if t.name in names]
    )
    if connection.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION preserve_freight_route_study() RETURNS trigger AS $$
            BEGIN IF TG_OP = 'DELETE' OR OLD.job_state IN ('COMPLETED','COMPLETED_STALE','FAILED')
            THEN RAISE EXCEPTION 'Route comparison history is immutable'; END IF;
            RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute(
            "CREATE TRIGGER preserve_route_study BEFORE UPDATE OR DELETE "
            "ON freight_route_studies FOR EACH ROW "
            "EXECUTE FUNCTION preserve_freight_route_study()"
        )
    else:
        op.execute(
            "CREATE TRIGGER preserve_route_study_update BEFORE UPDATE ON freight_route_studies "
            "WHEN OLD.job_state IN ('COMPLETED','COMPLETED_STALE','FAILED') "
            "BEGIN SELECT RAISE(ABORT, 'Route comparison history is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER preserve_route_study_delete BEFORE DELETE ON freight_route_studies "
            "BEGIN SELECT RAISE(ABORT, 'Route comparison history is immutable'); END"
        )


def downgrade():
    raise RuntimeError("Forward repair required; route comparison evidence must be retained")
