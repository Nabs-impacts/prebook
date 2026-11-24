from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit_log import AdminAuditLog
from app.models.enums import AdminAuditAction, UserRole
from app.models.user import User

ADMIN_ROLES = (UserRole.ADMIN, UserRole.SUPER_ADMIN)


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID, for_update: bool = False) -> User | None:
        statement = select(User).where(User.id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(func.lower(User.email) == email.strip().lower())
        return await self._session.scalar(statement)

    async def list_admins(self, offset: int, limit: int) -> list[User]:
        statement = (
            select(User)
            .where(User.role.in_(ADMIN_ROLES))
            .order_by(User.created_at.desc(), User.email.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def count_admins(self) -> int:
        statement = select(func.count()).select_from(User).where(User.role.in_(ADMIN_ROLES))
        return int(await self._session.scalar(statement) or 0)

    async def count_active_super_admins(self, exclude_id: UUID | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(User)
            .where(
                User.role == UserRole.SUPER_ADMIN,
                User.is_active.is_(True),
            )
        )
        if exclude_id is not None:
            statement = statement.where(User.id != exclude_id)
        return int(await self._session.scalar(statement) or 0)

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        await self._session.delete(user)
        await self._session.flush()

    async def add_audit_log(
        self,
        admin_id: UUID | None,
        action: AdminAuditAction,
        target_id: UUID | None,
        ip: str | None,
        *,
        target_key: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
    ) -> AdminAuditLog:
        audit_log = AdminAuditLog(
            admin_id=admin_id,
            action=action,
            target_id=target_id,
            target_key=target_key,
            old_value=old_value,
            new_value=new_value,
            ip=ip,
        )
        self._session.add(audit_log)
        await self._session.flush()
        return audit_log

    async def commit(self) -> None:
        await self._session.commit()
