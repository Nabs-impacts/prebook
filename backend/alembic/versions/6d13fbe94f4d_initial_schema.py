from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6d13fbe94f4d"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ebooks",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("cover_url", sa.String(length=1024), nullable=False),
        sa.Column("pdf_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("preview_video_id", sa.String(length=255), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_ebooks_price_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ebooks")),
        sa.UniqueConstraint("slug", name=op.f("uq_ebooks_slug")),
    )
    op.create_index(op.f("ix_ebooks_created_at"), "ebooks", ["created_at"], unique=False)
    op.create_index(
        "ix_ebooks_is_published_created_at", "ebooks", ["is_published", "created_at"], unique=False
    )
    op.create_index("ix_ebooks_price", "ebooks", ["price"], unique=False)
    op.create_table(
        "page_views",
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("visitor_hash", sa.String(length=64), nullable=False),
        sa.Column("referrer", sa.String(length=2048), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_views")),
    )
    op.create_index(op.f("ix_page_views_created_at"), "page_views", ["created_at"], unique=False)
    op.create_index(
        "ix_page_views_path_created_at", "page_views", ["path", "created_at"], unique=False
    )
    op.create_index(
        "ix_page_views_visitor_hash_created_at",
        "page_views",
        ["visitor_hash", "created_at"],
        unique=False,
    )
    op.create_table(
        "site_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_site_settings")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("customer", "admin", "super_admin", name="user_role"),
            server_default="customer",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"], unique=False)
    op.create_index("ix_users_is_active", "users", ["is_active"], unique=False)
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_table(
        "orders",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("buyer_email", sa.String(length=320), nullable=False),
        sa.Column("buyer_name", sa.String(length=255), nullable=False),
        sa.Column("ebook_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="XOF", nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "paid", "failed", "refunded", name="order_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_orders_amount_non_negative")),
        sa.ForeignKeyConstraint(
            ["ebook_id"], ["ebooks.id"], name=op.f("fk_orders_ebook_id_ebooks"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_orders_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("provider", "provider_reference", name="uq_orders_provider_reference"),
    )
    op.create_index("ix_orders_buyer_email", "orders", ["buyer_email"], unique=False)
    op.create_index(op.f("ix_orders_created_at"), "orders", ["created_at"], unique=False)
    op.create_index(
        "ix_orders_ebook_id_created_at", "orders", ["ebook_id", "created_at"], unique=False
    )
    op.create_index("ix_orders_paid_at", "orders", ["paid_at"], unique=False)
    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"], unique=False)
    op.create_index(
        "ix_orders_user_id_created_at", "orders", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "reviews",
        sa.Column("ebook_id", sa.UUID(), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_approved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name=op.f("ck_reviews_rating_range")),
        sa.ForeignKeyConstraint(
            ["ebook_id"], ["ebooks.id"], name=op.f("fk_reviews_ebook_id_ebooks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index(op.f("ix_reviews_created_at"), "reviews", ["created_at"], unique=False)
    op.create_index(
        "ix_reviews_ebook_id_is_approved_created_at",
        "reviews",
        ["ebook_id", "is_approved", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reviews_is_approved_created_at", "reviews", ["is_approved", "created_at"], unique=False
    )
    op.create_index("ix_reviews_rating", "reviews", ["rating"], unique=False)
    op.create_table(
        "download_tokens",
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_downloads", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("download_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "download_count >= 0", name=op.f("ck_download_tokens_download_count_non_negative")
        ),
        sa.CheckConstraint(
            "max_downloads > 0", name=op.f("ck_download_tokens_max_downloads_positive")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_download_tokens_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_download_tokens_token_hash")),
    )
    op.create_index(
        "ix_download_tokens_expires_at", "download_tokens", ["expires_at"], unique=False
    )
    op.create_index("ix_download_tokens_order_id", "download_tokens", ["order_id"], unique=False)
    op.create_table(
        "watermarked_files",
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("watermark_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_watermarked_files_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watermarked_files")),
        sa.UniqueConstraint("watermark_id", name=op.f("uq_watermarked_files_watermark_id")),
    )
    op.create_index(
        op.f("ix_watermarked_files_created_at"), "watermarked_files", ["created_at"], unique=False
    )
    op.create_index(
        "ix_watermarked_files_order_id", "watermarked_files", ["order_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_watermarked_files_order_id", table_name="watermarked_files")
    op.drop_index(op.f("ix_watermarked_files_created_at"), table_name="watermarked_files")
    op.drop_table("watermarked_files")
    op.drop_index("ix_download_tokens_order_id", table_name="download_tokens")
    op.drop_index("ix_download_tokens_expires_at", table_name="download_tokens")
    op.drop_table("download_tokens")
    op.drop_index("ix_reviews_rating", table_name="reviews")
    op.drop_index("ix_reviews_is_approved_created_at", table_name="reviews")
    op.drop_index("ix_reviews_ebook_id_is_approved_created_at", table_name="reviews")
    op.drop_index(op.f("ix_reviews_created_at"), table_name="reviews")
    op.drop_table("reviews")
    op.drop_index("ix_orders_user_id_created_at", table_name="orders")
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_index("ix_orders_paid_at", table_name="orders")
    op.drop_index("ix_orders_ebook_id_created_at", table_name="orders")
    op.drop_index(op.f("ix_orders_created_at"), table_name="orders")
    op.drop_index("ix_orders_buyer_email", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index(op.f("ix_users_created_at"), table_name="users")
    op.drop_table("users")
    op.drop_table("site_settings")
    op.drop_index("ix_page_views_visitor_hash_created_at", table_name="page_views")
    op.drop_index("ix_page_views_path_created_at", table_name="page_views")
    op.drop_index(op.f("ix_page_views_created_at"), table_name="page_views")
    op.drop_table("page_views")
    op.drop_index("ix_ebooks_price", table_name="ebooks")
    op.drop_index("ix_ebooks_is_published_created_at", table_name="ebooks")
    op.drop_index(op.f("ix_ebooks_created_at"), table_name="ebooks")
    op.drop_table("ebooks")
    postgresql.ENUM(name="order_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_role").drop(op.get_bind(), checkfirst=True)
