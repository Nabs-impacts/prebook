from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.review import Review
    from app.models.video import Video


class Ebook(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ebooks"
    __table_args__ = (
        Index("ix_ebooks_is_published_created_at", "is_published", "created_at"),
        Index(
            "ix_ebooks_is_published_deleted_at_created_at",
            "is_published",
            "deleted_at",
            "created_at",
        ),
        Index("ix_ebooks_price", "price"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    cover_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    pdf_storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    preview_video_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    orders: Mapped[list["Order"]] = relationship(back_populates="ebook", lazy="raise")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="ebook",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    videos: Mapped[list["Video"]] = relationship(
        back_populates="ebook",
        foreign_keys="Video.ebook_id",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    preview_video: Mapped["Video | None"] = relationship(
        foreign_keys=[preview_video_id],
        lazy="raise",
        post_update=True,
    )
