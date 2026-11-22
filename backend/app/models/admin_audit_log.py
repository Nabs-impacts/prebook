from typing import Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AdminAuditAction, enum_values
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class AdminAuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_admin_audit_logs_admin_id_created_at", "admin_id", "created_at"),
        Index("ix_admin_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_admin_audit_logs_target_id", "target_id"),
        Index("ix_admin_audit_logs_target_key", "target_key"),
    )

    admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[AdminAuditAction] = mapped_column(
        Enum(
            AdminAuditAction,
            name="admin_audit_action",
            values_callable=enum_values,
            native_enum=True,
        ),
        nullable=False,
    )
    target_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    target_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
