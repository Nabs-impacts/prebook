from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c1a7b3d902"
down_revision: str | None = "d7b2f4a9c1e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ebooks",
        sa.Column("summary", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "ebooks",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ebooks_is_published_deleted_at_created_at",
        "ebooks",
        ["is_published", "deleted_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_orders_ebook_id_status",
        "orders",
        ["ebook_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_ebook_id_status", table_name="orders")
    op.drop_index(
        "ix_ebooks_is_published_deleted_at_created_at",
        table_name="ebooks",
    )
    op.drop_column("ebooks", "deleted_at")
    op.drop_column("ebooks", "summary")
