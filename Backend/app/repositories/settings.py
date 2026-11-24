import json
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_setting import SiteSetting

SETTINGS_CACHE_KEY = "settings:site"
SETTINGS_CACHE_TTL_SECONDS = 300


class SettingsRepository:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis

    async def get_cached(self) -> dict[str, Any] | None:
        raw = await self._redis.get(SETTINGS_CACHE_KEY)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    async def cache(self, values: dict[str, Any]) -> None:
        await self._redis.set(
            SETTINGS_CACHE_KEY,
            json.dumps(values),
            ex=SETTINGS_CACHE_TTL_SECONDS,
        )

    async def invalidate(self) -> None:
        await self._redis.delete(SETTINGS_CACHE_KEY)

    async def load_all(self) -> dict[str, Any]:
        result = await self._session.scalars(select(SiteSetting))
        return {setting.key: setting.value for setting in result}

    async def save(self, values: dict[str, Any]) -> None:
        if not values:
            return
        statement = insert(SiteSetting).values(
            [{"key": key, "value": value} for key, value in values.items()]
        )
        statement = statement.on_conflict_do_update(
            index_elements=[SiteSetting.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
        await self._session.execute(statement)

    async def commit(self) -> None:
        await self._session.commit()
