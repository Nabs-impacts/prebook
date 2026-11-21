from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID, uuid4

from app.core.security import hash_password
from app.models.admin_audit_log import AdminAuditLog
from app.models.enums import AdminAuditAction, UserRole
from app.models.user import User
from app.repositories.admin import ADMIN_ROLES


class TokenBody(TypedDict):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.audit_logs: list[AdminAuditLog] = []

    async def get_by_id(self, user_id: UUID, for_update: bool = False) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        for user in self.users.values():
            if user.email.lower() == normalized:
                return user
        return None

    async def list_admins(self, offset: int, limit: int) -> list[User]:
        admins = [user for user in self.users.values() if user.role in ADMIN_ROLES]
        admins.sort(key=lambda user: (user.created_at, user.email), reverse=True)
        return admins[offset : offset + limit]

    async def count_admins(self) -> int:
        return sum(1 for user in self.users.values() if user.role in ADMIN_ROLES)

    async def count_active_super_admins(self, exclude_id: UUID | None = None) -> int:
        return sum(
            1
            for user in self.users.values()
            if user.role is UserRole.SUPER_ADMIN and user.is_active and user.id != exclude_id
        )

    async def create(self, user: User) -> User:
        user.id = uuid4()
        user.created_at = datetime.now(UTC)
        self.users[user.id] = user
        return user

    async def delete(self, user: User) -> None:
        self.users.pop(user.id, None)

    async def add_audit_log(
        self,
        admin_id: UUID | None,
        action: AdminAuditAction,
        target_id: UUID | None,
        ip: str | None,
    ) -> AdminAuditLog:
        audit_log = AdminAuditLog(
            admin_id=admin_id,
            action=action,
            target_id=target_id,
            ip=ip,
        )
        audit_log.id = uuid4()
        audit_log.created_at = datetime.now(UTC)
        self.audit_logs.append(audit_log)
        return audit_log

    async def commit(self) -> None:
        return None


def build_user(
    email: str,
    role: UserRole,
    password: str = "Password123!",
    is_active: bool = True,
) -> User:
    return User(
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )


async def seed_user(
    repository: InMemoryAdminRepository,
    email: str,
    role: UserRole,
    password: str = "Password123!",
    is_active: bool = True,
) -> User:
    return await repository.create(build_user(email, role, password, is_active))
