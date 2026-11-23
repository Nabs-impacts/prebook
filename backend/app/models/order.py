from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import OrderStatus, enum_values
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.download_token import DownloadToken
    from app.models.ebook import Ebook
    from app.models.user import User
    from app.models.watermarked_file import WatermarkedFile


class Order(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
        Index("ix_orders_ebook_id_created_at", "ebook_id", "created_at"),
        Index("ix_orders_ebook_id_status", "ebook_id", "status"),
        Index("ix_orders_status_created_at", "status", "created_at"),
        Index("ix_orders_buyer_email", "buyer_email"),
        Index("ix_orders_paid_at", "paid_at"),
        UniqueConstraint("provider", "provider_reference", name="uq_orders_provider_reference"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    buyer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ebook_id: Mapped[UUID] = mapped_column(
        ForeignKey("ebooks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="XOF",
        server_default="XOF",
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            name="order_status",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
        default=OrderStatus.PENDING,
        server_default=OrderStatus.PENDING.value,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="orders", lazy="raise")
    ebook: Mapped["Ebook"] = relationship(back_populates="orders", lazy="raise")
    download_tokens: Mapped[list["DownloadToken"]] = relationship(
        back_populates="order",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    watermarked_files: Mapped[list["WatermarkedFile"]] = relationship(
        back_populates="order",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
