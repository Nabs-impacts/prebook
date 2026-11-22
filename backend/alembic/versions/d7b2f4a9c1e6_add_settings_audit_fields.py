from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7b2f4a9c1e6"
down_revision: str | None = "c3a9e5f7b2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_audit_logs",
        sa.Column("target_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_admin_audit_logs_target_key",
        "admin_audit_logs",
        ["target_key"],
        unique=False,
    )
    op.execute("ALTER TYPE admin_audit_action ADD VALUE IF NOT EXISTS 'settings_updated'")


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_target_key", table_name="admin_audit_logs")
    op.drop_column("admin_audit_logs", "new_value")
    op.drop_column("admin_audit_logs", "old_value")
    op.drop_column("admin_audit_logs", "target_key")
