from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.db.session import get_redis_client, get_session_factory
from app.models.enums import AdminAuditAction
from app.models.user import User
from app.repositories.admin import AdminRepository
from app.repositories.settings import SettingsRepository
from app.schemas.settings import SiteSettings, SiteSettingsUpdate


@dataclass(frozen=True, slots=True)
class OptionalCounts:
    reviews_count: int | None
    purchases_count: int | None


class SettingsService:
    def __init__(
        self,
        settings_repository: SettingsRepository,
        admin_repository: AdminRepository,
    ) -> None:
        self._settings_repository = settings_repository
        self._admin_repository = admin_repository

    def _validate(self, values: Mapping[str, Any]) -> SiteSettings:
        allowed = set(SiteSettings.model_fields)
        return SiteSettings.model_validate(
            {key: value for key, value in values.items() if key in allowed}
        )

    async def get_settings(self) -> SiteSettings:
        cached = await self._settings_repository.get_cached()
        if cached is not None:
            try:
                return self._validate(cached)
            except ValidationError:
                await self._settings_repository.invalidate()
        stored = await self._settings_repository.load_all()
        settings = self._validate(stored)
        await self._settings_repository.cache(settings.model_dump())
        return settings

    async def update_settings(
        self,
        actor: User,
        data: SiteSettingsUpdate,
        ip: str | None,
    ) -> SiteSettings:
        current = await self.get_settings()
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        updated = current.model_copy(update=changes)
        await self._settings_repository.save(changes)
        for key, new_value in changes.items():
            await self._admin_repository.add_audit_log(
                actor.id,
                AdminAuditAction.SETTINGS_UPDATED,
                None,
                ip,
                target_key=key,
                old_value=getattr(current, key),
                new_value=new_value,
            )
        await self._settings_repository.commit()
        await self._settings_repository.invalidate()
        await self._settings_repository.cache(updated.model_dump())
        return updated

    async def resolve_optional_counts(
        self,
        review_counter: Callable[[], Awaitable[int]],
        purchase_counter: Callable[[], Awaitable[int]],
        *,
        settings: SiteSettings | None = None,
    ) -> OptionalCounts:
        current = settings if settings is not None else await self.get_settings()
        reviews_count = await review_counter() if current.show_reviews_count else None
        purchases_count = await purchase_counter() if current.show_purchases_count else None
        return OptionalCounts(
            reviews_count=reviews_count,
            purchases_count=purchases_count,
        )


async def load_maintenance_settings() -> SiteSettings:
    async with get_session_factory()() as session:
        repository = SettingsRepository(session, get_redis_client())
        service = SettingsService(repository, AdminRepository(session))
        return await service.get_settings()
