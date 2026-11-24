from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "f8a2c4d6e910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("payment_url", sa.String(length=2048), nullable=True))
    op.add_column("orders", sa.Column("payment_instructions", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_orders_idempotency_key",
        "orders",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_orders_payment_method_created_at",
        "orders",
        ["payment_method", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_payment_method_created_at", table_name="orders")
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "payment_instructions")
    op.drop_column("orders", "payment_url")
    op.drop_column("orders", "idempotency_key")
    op.drop_column("orders", "payment_method")
