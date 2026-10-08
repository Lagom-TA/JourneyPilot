"""Durable worker invocation snapshots, independent of graph checkpoints."""
from alembic import op

revision = "0009_worker_journal"
down_revision = "0008_llm_usage_details"
branch_labels = depends_on = None
destructive = False
reversible = True


def upgrade():
    op.execute("""
        CREATE TABLE run_worker_journals (
            run_id TEXT NOT NULL REFERENCES trip_runs(run_id) ON DELETE CASCADE,
            scope_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            payload_type TEXT NOT NULL,
            payload BYTEA NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (run_id, scope_id)
        )
    """)


def downgrade():
    op.execute("DROP TABLE run_worker_journals")
