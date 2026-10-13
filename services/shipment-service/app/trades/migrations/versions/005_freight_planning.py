"""Add retained freight planning without another movement or booking ledger."""

import sqlalchemy as sa
from alembic import op
from app.freight.models import IMMUTABLE_TABLES, TABLES
from app.trades.models import TradeBase

revision = "trade_005"
down_revision = "trade_004"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    names = {m.__tablename__ for m in TABLES}
    TradeBase.metadata.create_all(
        connection, tables=[t for t in TradeBase.metadata.sorted_tables if t.name in names]
    )
    columns = {c["name"] for c in sa.inspect(connection).get_columns("op_vehicles")}
    if "current_routing_profile_revision_id" not in columns:
        op.add_column(
            "op_vehicles",
            sa.Column("current_routing_profile_revision_id", sa.Uuid(), nullable=True),
        )
    if "execution_mode" not in columns:
        op.add_column(
            "op_vehicles",
            sa.Column("execution_mode", sa.String(20), nullable=False, server_default="PRODUCTION"),
        )
        op.execute(
            "UPDATE op_vehicles SET execution_mode = 'SIMULATION' WHERE id IN "
            "(SELECT a.vehicle_id FROM op_transport_assignments a "
            "JOIN op_consignments c ON c.id = a.consignment_id "
            "WHERE c.execution_mode = 'SIMULATION') AND id NOT IN "
            "(SELECT a.vehicle_id FROM op_transport_assignments a "
            "JOIN op_consignments c ON c.id = a.consignment_id "
            "WHERE c.execution_mode = 'PRODUCTION' AND a.vehicle_id IS NOT NULL)"
        )
    evidence_columns = {
        c["name"]: c for c in sa.inspect(connection).get_columns("transport_evidence_revisions")
    }
    if not evidence_columns["assignment_id"]["nullable"]:
        with op.batch_alter_table("transport_evidence_revisions") as batch:
            batch.alter_column("assignment_id", existing_type=sa.Uuid(), nullable=True)
        if connection.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    "CREATE TRIGGER IF NOT EXISTS "
                    f"transport_evidence_revisions_immutable_{action.lower()} "
                    f"BEFORE {action} ON transport_evidence_revisions "
                    "BEGIN SELECT RAISE(ABORT, 'Compliance evidence is immutable'); END"
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
                    f"CREATE TRIGGER {table}_immutable_{action.lower()} "
                    f"BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Freight evidence is immutable'); END"
                )
    if connection.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION freight_preserve_run() RETURNS trigger AS $$
            BEGIN IF OLD.job_state IN ('COMPLETED','FAILED','CANCELLED') OR TG_OP = 'DELETE'
            THEN RAISE EXCEPTION 'Completed run is immutable'; END IF; RETURN NEW; END;
            $$ LANGUAGE plpgsql""")
        op.execute(
            "CREATE TRIGGER immutable_completed_run BEFORE UPDATE OR DELETE "
            "ON tradetwin_runs FOR EACH ROW EXECUTE FUNCTION freight_preserve_run()"
        )
    else:
        op.execute(
            "CREATE TRIGGER immutable_completed_run BEFORE UPDATE ON tradetwin_runs "
            "WHEN OLD.job_state IN ('COMPLETED','FAILED','CANCELLED') "
            "BEGIN SELECT RAISE(ABORT, 'Completed run is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER immutable_run_delete BEFORE DELETE ON tradetwin_runs "
            "BEGIN SELECT RAISE(ABORT, 'Run history is immutable'); END"
        )
    preserve_rfq(connection)
    if connection.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER immutable_completed_generation BEFORE UPDATE OR DELETE "
            "ON routing_generation_jobs FOR EACH ROW EXECUTE FUNCTION freight_preserve_run()"
        )
    else:
        op.execute(
            "CREATE TRIGGER immutable_completed_generation BEFORE UPDATE "
            "ON routing_generation_jobs WHEN OLD.job_state IN ('COMPLETED','FAILED','CANCELLED') "
            "BEGIN SELECT RAISE(ABORT, 'Completed generation is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER immutable_generation_delete BEFORE DELETE "
            "ON routing_generation_jobs "
            "BEGIN SELECT RAISE(ABORT, 'Generation history is immutable'); END"
        )


def preserve_rfq(connection):
    columns = [
        c["name"]
        for c in sa.inspect(connection).get_columns("freight_rfqs")
        if c["name"] not in {"lifecycle_projection", "row_version", "updated_at"}
    ]
    if connection.dialect.name == "postgresql":
        old = ", ".join(f"OLD.{c}" for c in columns)
        new = ", ".join(f"NEW.{c}" for c in columns)
        op.execute(f"""CREATE FUNCTION freight_preserve_rfq() RETURNS trigger AS $$
            BEGIN IF TG_OP = 'DELETE' OR
            (OLD.lifecycle_projection <> 'DRAFT' AND
             ROW({old}) IS DISTINCT FROM ROW({new})) THEN
            RAISE EXCEPTION 'Published RFQ is immutable'; END IF; RETURN NEW; END;
            $$ LANGUAGE plpgsql""")
        op.execute(
            "CREATE TRIGGER preserve_rfq BEFORE UPDATE OR DELETE ON freight_rfqs "
            "FOR EACH ROW EXECUTE FUNCTION freight_preserve_rfq()"
        )
    else:
        differs = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        op.execute(
            "CREATE TRIGGER preserve_rfq BEFORE UPDATE ON freight_rfqs "
            f"WHEN OLD.lifecycle_projection <> 'DRAFT' AND ({differs}) "
            "BEGIN SELECT RAISE(ABORT, 'Published RFQ is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER preserve_rfq_delete BEFORE DELETE ON freight_rfqs "
            "BEGIN SELECT RAISE(ABORT, 'RFQ history is immutable'); END"
        )


def downgrade():
    raise RuntimeError(
        "Freight commitments cannot be destructively downgraded; restore a verified backup"
    )
