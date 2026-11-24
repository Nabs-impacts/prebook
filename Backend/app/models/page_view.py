from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class PageView(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "page_views"
    __table_args__ = (
        Index("ix_page_views_path_created_at", "path", "created_at"),
        Index("ix_page_views_visitor_hash_created_at", "visitor_hash", "created_at"),
    )

    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    visitor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    referrer: Mapped[str | None] = mapped_column(String(2048), nullable=True)
