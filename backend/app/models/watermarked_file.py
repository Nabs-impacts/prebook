from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.order import Order


class WatermarkedFile(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "watermarked_files"
    __table_args__ = (Index("ix_watermarked_files_order_id", "order_id"),)

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    watermark_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    order: Mapped["Order"] = relationship(
        back_populates="watermarked_files",
        lazy="raise",
    )
