"""Add scoped application compliance, preserving historical operational evidence."""

import sqlalchemy as sa
from alembic import op
from app.compliance.models import IMMUTABLE_TABLES, TABLES
from app.trades.models import TradeBase

revision = "trade_004"
down_revision = "trade_003"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    names = {model.__tablename__ for model in TABLES}
    TradeBase.metadata.create_all(
        connection, tables=[t for t in TradeBase.metadata.sorted_tables if t.name in names]
    )
    columns = {c["name"] for c in sa.inspect(connection).get_columns("op_consignments")}
    if "phase4_legacy_movement" not in columns:
        op.add_column(
            "op_consignments",
            sa.Column(
                "phase4_legacy_movement", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    op.execute(
        "UPDATE op_consignments SET phase4_legacy_movement = true "
        "WHERE movement_status != 'NOT_STARTED'"
    )
    job_columns = {c["name"]: c for c in sa.inspect(connection).get_columns("doc_processing_jobs")}
    if "trade_id" not in job_columns:
        op.add_column(
            "doc_processing_jobs",
            sa.Column("trade_id", sa.Uuid(), sa.ForeignKey("trades.id"), nullable=True),
        )
    if not job_columns["document_version_id"]["nullable"]:
        with op.batch_alter_table("doc_processing_jobs") as batch:
            batch.alter_column("document_version_id", existing_type=sa.Uuid(), nullable=True)
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
                    "BEGIN SELECT RAISE(ABORT, 'Compliance evidence is immutable'); END"
                )
    if connection.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION compliance_preserve_evaluation() RETURNS trigger AS $$
            BEGIN IF OLD.job_state IN ('COMPLETED', 'COMPLETED_STALE', 'FAILED', 'CANCELLED')
            OR TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Completed evaluation is immutable'; END IF; RETURN NEW; END;
            $$ LANGUAGE plpgsql""")
        op.execute(
            "CREATE TRIGGER immutable_completed_evaluation BEFORE UPDATE OR DELETE "
            "ON compliance_evaluations FOR EACH ROW "
            "EXECUTE FUNCTION compliance_preserve_evaluation()"
        )
    else:
        op.execute(
            "CREATE TRIGGER immutable_completed_evaluation BEFORE UPDATE ON compliance_evaluations "
            "WHEN OLD.job_state IN ('COMPLETED', 'COMPLETED_STALE', 'FAILED', 'CANCELLED') "
            "BEGIN SELECT RAISE(ABORT, 'Completed evaluation is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER immutable_evaluation_delete BEFORE DELETE ON compliance_evaluations "
            "BEGIN SELECT RAISE(ABORT, 'Evaluation history is immutable'); END"
        )
    preserve_core(
        connection,
        "dispatch_authorizations",
        {"consumed_event_id", "revoked_at", "revocation_reason"},
        "OLD.consumed_event_id IS NOT NULL OR OLD.revoked_at IS NOT NULL",
    )
    preserve_core(
        connection,
        "movement_document_reservations",
        {"released_at", "first_consumed_movement_event_id"},
        "OLD.released_at IS NOT NULL OR "
        "(OLD.first_consumed_movement_event_id IS NOT NULL AND NEW.released_at IS NOT NULL)",
    )


def preserve_core(connection, table, mutable, terminal):
    columns = [
        c["name"] for c in sa.inspect(connection).get_columns(table) if c["name"] not in mutable
    ]
    if connection.dialect.name == "postgresql":
        old = ", ".join(f"OLD.{c}" for c in columns)
        new = ", ".join(f"NEW.{c}" for c in columns)
        op.execute(f"""CREATE FUNCTION preserve_{table}() RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Dispatch history is immutable'; END IF;
              IF ROW({old}) IS DISTINCT FROM ROW({new}) OR ({terminal}) THEN
                RAISE EXCEPTION 'Dispatch core is immutable';
              END IF;
              RETURN NEW;
            END; $$ LANGUAGE plpgsql""")
        op.execute(
            f"CREATE TRIGGER preserve_core BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION preserve_{table}()"
        )
    else:
        differs = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        op.execute(
            f"CREATE TRIGGER preserve_{table}_update BEFORE UPDATE ON {table} "
            f"WHEN ({differs}) OR ({terminal}) "
            "BEGIN SELECT RAISE(ABORT, 'Dispatch core is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER preserve_{table}_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'Dispatch history is immutable'); END"
        )


def downgrade():
    raise RuntimeError(
        "Compliance decisions and authorisation history cannot be destructively downgraded; "
        "restore a verified backup"
    )
