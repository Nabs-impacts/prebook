from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e6f8b1c3"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'expired'")
    op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'manual_review'")
    op.execute("ALTER TYPE admin_audit_action ADD VALUE IF NOT EXISTS 'payment_manual_review'")
    op.execute("ALTER TYPE admin_audit_action ADD VALUE IF NOT EXISTS 'order_refunded'")
    op.execute("ALTER TYPE admin_audit_action ADD VALUE IF NOT EXISTS 'order_rechecked'")
    op.add_column(
        "orders",
        sa.Column("payment_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_failure_reason", sa.Text(), nullable=True),
    )
    op.drop_index("ix_orders_payment_method_created_at", table_name="orders")
    op.drop_column("orders", "payment_method")
    op.drop_column("orders", "payment_instructions")
    op.execute(
        "DELETE FROM site_settings WHERE key IN "
        "('payment_mynita_enabled', 'payment_amanata_enabled', 'payment_airtel_money_enabled')"
    )
    op.execute(
        "INSERT INTO site_settings (key, value) VALUES ('payments_enabled', 'true'::jsonb) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM site_settings WHERE key = 'payments_enabled'")
    op.execute(
        "INSERT INTO site_settings (key, value) VALUES "
        "('payment_mynita_enabled', 'true'::jsonb), "
        "('payment_amanata_enabled', 'true'::jsonb), "
        "('payment_airtel_money_enabled', 'true'::jsonb) "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.add_column(
        "orders",
        sa.Column("payment_instructions", sa.Text(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "payment_method",
            sa.String(length=50),
            server_default="",
            nullable=False,
        ),
    )
    op.alter_column("orders", "payment_method", server_default=None)
    op.create_index(
        "ix_orders_payment_method_created_at",
        "orders",
        ["payment_method", "created_at"],
        unique=False,
    )
    op.drop_column("orders", "payment_failure_reason")
    op.drop_column("orders", "payment_expires_at")
