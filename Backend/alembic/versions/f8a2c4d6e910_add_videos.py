from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a2c4d6e910"
down_revision: str | None = "e5c1a7b3d902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("ebook_id", sa.UUID(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("cloudflare_stream", "external_url", name="video_provider"),
            nullable=False,
        ),
        sa.Column("provider_video_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "status",
            sa.Enum("uploading", "processing", "ready", "failed", name="video_status"),
            server_default="uploading",
            nullable=False,
        ),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
        sa.Column("hls_url", sa.String(length=1024), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ebook_id"],
            ["ebooks.id"],
            name=op.f("fk_videos_ebook_id_ebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_videos")),
    )
    op.create_index(op.f("ix_videos_created_at"), "videos", ["created_at"], unique=False)
    op.create_index(
        "ix_videos_ebook_id_created_at",
        "videos",
        ["ebook_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_videos_provider_video_id",
        "videos",
        ["provider", "provider_video_id"],
        unique=False,
    )
    op.create_index("ix_videos_status", "videos", ["status"], unique=False)

    op.drop_column("ebooks", "preview_video_id")
    op.add_column("ebooks", sa.Column("preview_video_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ebooks_preview_video_id_videos"),
        "ebooks",
        "videos",
        ["preview_video_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ebooks_preview_video_id_videos"),
        "ebooks",
        type_="foreignkey",
    )
    op.drop_column("ebooks", "preview_video_id")
    op.add_column(
        "ebooks",
        sa.Column("preview_video_id", sa.String(length=255), nullable=True),
    )

    op.drop_index("ix_videos_status", table_name="videos")
    op.drop_index("ix_videos_provider_video_id", table_name="videos")
    op.drop_index("ix_videos_ebook_id_created_at", table_name="videos")
    op.drop_index(op.f("ix_videos_created_at"), table_name="videos")
    op.drop_table("videos")
    postgresql.ENUM(name="video_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="video_provider").drop(op.get_bind(), checkfirst=True)
