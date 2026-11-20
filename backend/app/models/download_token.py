from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.order import Order


class DownloadToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "download_tokens"
    __table_args__ = (
        Index("ix_download_tokens_order_id", "order_id"),
        Index("ix_download_tokens_expires_at", "expires_at"),
        CheckConstraint("max_downloads > 0", name="max_downloads_positive"),
        CheckConstraint("download_count >= 0", name="download_count_non_negative"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_downloads: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    download_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    order: Mapped["Order"] = relationship(
        back_populates="download_tokens",
        lazy="raise",
    )
