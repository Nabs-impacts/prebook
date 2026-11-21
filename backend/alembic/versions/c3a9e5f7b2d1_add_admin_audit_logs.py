from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3a9e5f7b2d1"
down_revision: str | None = "6d13fbe94f4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_logs",
        sa.Column("admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "login",
                "login_failed",
                "admin_created",
                "admin_updated",
                "admin_deleted",
                name="admin_audit_action",
            ),
            nullable=False,
        ),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["users.id"],
            name=op.f("fk_admin_audit_logs_admin_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_logs")),
    )
    op.create_index(
        op.f("ix_admin_audit_logs_created_at"),
        "admin_audit_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_audit_logs_admin_id_created_at",
        "admin_audit_logs",
        ["admin_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_audit_logs_action_created_at",
        "admin_audit_logs",
        ["action", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_audit_logs_target_id",
        "admin_audit_logs",
        ["target_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_target_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action_created_at", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_admin_id_created_at", table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_created_at"), table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
    postgresql.ENUM(name="admin_audit_action").drop(op.get_bind(), checkfirst=True)
