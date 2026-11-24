from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import VideoProviderType, VideoStatus, enum_values
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ebook import Ebook


class Video(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_ebook_id_created_at", "ebook_id", "created_at"),
        Index("ix_videos_provider_video_id", "provider", "provider_video_id"),
        Index("ix_videos_status", "status"),
    )

    ebook_id: Mapped[UUID] = mapped_column(
        ForeignKey("ebooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[VideoProviderType] = mapped_column(
        Enum(
            VideoProviderType,
            name="video_provider",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    provider_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[VideoStatus] = mapped_column(
        Enum(
            VideoStatus,
            name="video_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        default=VideoStatus.UPLOADING,
        server_default=VideoStatus.UPLOADING.value,
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    hls_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    ebook: Mapped["Ebook"] = relationship(
        back_populates="videos",
        foreign_keys=[ebook_id],
        lazy="raise",
    )
