from typing import Protocol
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings


class TaskQueue(Protocol):
    async def enqueue_fulfill_order(self, order_id: UUID) -> None: ...


class ArqTaskQueue:
    async def enqueue_fulfill_order(self, order_id: UUID) -> None:
        pool = await create_pool(RedisSettings.from_dsn(get_settings().REDIS_URL))
        try:
            await pool.enqueue_job("fulfill_order", str(order_id))
        finally:
            await pool.aclose()
