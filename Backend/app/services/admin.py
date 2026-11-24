from math import ceil
from uuid import UUID

from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.enums import AdminAuditAction, UserRole
from app.models.user import User
from app.repositories.admin import AdminRepository
from app.repositories.token import TokenRepository
from app.schemas.admin import AdminCreate, AdminListResponse, AdminRead, AdminUpdate

SELF_DELETE_MESSAGE = "Un super administrateur ne peut pas se supprimer lui-même."
SELF_DEACTIVATE_MESSAGE = "Un super administrateur ne peut pas se désactiver lui-même."
LAST_SUPER_ADMIN_MESSAGE = "Impossible de supprimer ou désactiver le dernier super administrateur."
EMAIL_CONFLICT_MESSAGE = "Un compte existe déjà avec cet email."


class AdminService:
    def __init__(
        self,
        admin_repository: AdminRepository,
        token_repository: TokenRepository,
    ) -> None:
        self._admin_repository = admin_repository
        self._token_repository = token_repository

    async def list_admins(self, page: int, page_size: int) -> AdminListResponse:
        offset = (page - 1) * page_size
        users, total = await self._list_page(offset, page_size)
        return AdminListResponse(
            items=[AdminRead.model_validate(user) for user in users],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    async def _list_page(self, offset: int, page_size: int) -> tuple[list[User], int]:
        users = await self._admin_repository.list_admins(offset, page_size)
        total = await self._admin_repository.count_admins()
        return users, total

    async def create_admin(self, actor: User, data: AdminCreate, ip: str | None) -> AdminRead:
        email = str(data.email).strip().lower()
        existing = await self._admin_repository.get_by_email(email)
        if existing is not None:
            raise ConflictError(EMAIL_CONFLICT_MESSAGE)

        user = User(
            email=email,
            password_hash=hash_password(data.password),
            role=data.role,
            is_active=True,
        )
        created = await self._admin_repository.create(user)
        await self._admin_repository.add_audit_log(
            actor.id,
            AdminAuditAction.ADMIN_CREATED,
            created.id,
            ip,
        )
        await self._admin_repository.commit()
        return AdminRead.model_validate(created)

    async def update_admin(
        self,
        actor: User,
        target_id: UUID,
        data: AdminUpdate,
        ip: str | None,
    ) -> AdminRead:
        target = await self._admin_repository.get_by_id(target_id, for_update=True)
        if target is None:
            raise NotFoundError("Administrateur introuvable.")

        password_changed = False
        deactivated = False

        if data.is_active is not None and data.is_active != target.is_active:
            if not data.is_active:
                if target.id == actor.id:
                    raise ConflictError(SELF_DEACTIVATE_MESSAGE)
                if target.role is UserRole.SUPER_ADMIN and target.is_active:
                    remaining = await self._admin_repository.count_active_super_admins(
                        exclude_id=target.id
                    )
                    if remaining < 1:
                        raise ConflictError(LAST_SUPER_ADMIN_MESSAGE)
                deactivated = True
            target.is_active = data.is_active

        if data.password is not None:
            target.password_hash = hash_password(data.password)
            password_changed = True

        await self._admin_repository.add_audit_log(
            actor.id,
            AdminAuditAction.ADMIN_UPDATED,
            target.id,
            ip,
        )
        await self._admin_repository.commit()

        if password_changed or deactivated:
            await self._token_repository.revoke_all_for_user(target.id)
        return AdminRead.model_validate(target)

    async def delete_admin(self, actor: User, target_id: UUID, ip: str | None) -> None:
        target = await self._admin_repository.get_by_id(target_id, for_update=True)
        if target is None:
            raise NotFoundError("Administrateur introuvable.")
        if target.id == actor.id:
            raise ConflictError(SELF_DELETE_MESSAGE)
        if target.role is UserRole.SUPER_ADMIN and target.is_active:
            remaining = await self._admin_repository.count_active_super_admins(exclude_id=target.id)
            if remaining < 1:
                raise ConflictError(LAST_SUPER_ADMIN_MESSAGE)

        await self._admin_repository.delete(target)
        await self._admin_repository.add_audit_log(
            actor.id,
            AdminAuditAction.ADMIN_DELETED,
            target.id,
            ip,
        )
        await self._admin_repository.commit()
        await self._token_repository.revoke_all_for_user(target.id)
