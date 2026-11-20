from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_redis_client, get_session
from app.repositories.health import HealthRepository
from app.services.health import HealthService

DbSession = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis_client)]


def get_health_service(session: DbSession, redis: RedisClient) -> HealthService:
    return HealthService(HealthRepository(session, redis))


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
