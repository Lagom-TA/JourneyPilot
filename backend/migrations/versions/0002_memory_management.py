"""记录用户对记忆的手动管理。"""

from alembic import op

revision = "0002_memory_management"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

destructive = False
reversible = True


def upgrade() -> None:
    op.execute("ALTER TABLE user_profiles ADD COLUMN memory_management_history JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE memory_facts ADD COLUMN memory_revision INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE memory_relations ADD COLUMN memory_revision INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE memory_relations DROP COLUMN memory_revision")
    op.execute("ALTER TABLE memory_facts DROP COLUMN memory_revision")
    op.execute("ALTER TABLE user_profiles DROP COLUMN memory_management_history")
