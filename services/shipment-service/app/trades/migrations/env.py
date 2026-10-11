from alembic import context
from app.trades.models import TradeBase

connection = context.config.attributes["connection"]
context.configure(
    connection=connection, target_metadata=TradeBase.metadata, version_table="trade_alembic_version"
)
with context.begin_transaction():
    context.run_migrations()
