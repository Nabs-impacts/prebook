from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthRepository:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis

    async def check_database(self) -> None:
        await self._session.execute(text("SELECT 1"))

    async def check_redis(self) -> None:
        await self._redis.ping()
