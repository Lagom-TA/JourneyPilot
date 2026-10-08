"""Retain cache writes, usage coverage and individual model attempts.

Historical bills are snapshots. Missing historical cache-write counts cannot
be reconstructed; mark legacy usage incomplete rather than inventing zeros.
"""

from alembic import op

revision = "0008_llm_usage_details"
down_revision = "0007_chat_turn_id"
branch_labels = None
depends_on = None
destructive = False
reversible = True


def upgrade() -> None:
    op.execute("""
        ALTER TABLE run_llm_calls
        ADD COLUMN cache_write_input_tokens INTEGER,
        ADD COLUMN total_tokens INTEGER,
        ADD COLUMN usage_complete BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN usage_source TEXT NOT NULL DEFAULT 'legacy',
        ADD COLUMN logical_call_id TEXT,
        ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1,
        ADD COLUMN request_input_tokens_estimate INTEGER,
        ADD COLUMN tool_schema_tokens_estimate INTEGER,
        ADD COLUMN finish_reason TEXT
    """)
    op.execute("""
        UPDATE run_llm_calls SET total_tokens = input_tokens + output_tokens
        WHERE input_tokens IS NOT NULL AND output_tokens IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE run_llm_calls
        DROP COLUMN finish_reason,
        DROP COLUMN tool_schema_tokens_estimate,
        DROP COLUMN request_input_tokens_estimate,
        DROP COLUMN attempt_number,
        DROP COLUMN logical_call_id,
        DROP COLUMN usage_source,
        DROP COLUMN usage_complete,
        DROP COLUMN total_tokens,
        DROP COLUMN cache_write_input_tokens
    """)
