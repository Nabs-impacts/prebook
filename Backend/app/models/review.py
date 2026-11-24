from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ebook import Ebook


class Review(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index(
            "ix_reviews_ebook_id_is_approved_created_at",
            "ebook_id",
            "is_approved",
            "created_at",
        ),
        Index("ix_reviews_is_approved_created_at", "is_approved", "created_at"),
        Index("ix_reviews_rating", "rating"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
    )

    ebook_id: Mapped[UUID] = mapped_column(
        ForeignKey("ebooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    ebook: Mapped["Ebook"] = relationship(back_populates="reviews", lazy="raise")
