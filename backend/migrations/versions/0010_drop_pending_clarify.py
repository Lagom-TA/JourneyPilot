"""Drop the pre-run intake draft column; understanding now lives in run checkpoints."""

from alembic import op

revision = "0010_drop_pending_clarify"
down_revision = "0009_worker_journal"
branch_labels = depends_on = None
destructive = True
reversible = False


def upgrade():
    op.execute("ALTER TABLE chat_sessions DROP COLUMN pending_clarify")
