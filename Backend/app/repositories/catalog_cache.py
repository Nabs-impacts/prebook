from typing import Literal
from uuid import UUID

from redis.asyncio import Redis

CATALOG_VERSION_KEY = "catalog:version"
RESPONSE_CACHE_TTL_SECONDS = 120
COUNTER_CACHE_TTL_SECONDS = 600

CounterName = Literal["reviews", "purchases"]


class CatalogCacheRepository:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_version(self) -> int:
        raw = await self._redis.get(CATALOG_VERSION_KEY)
        if raw is None:
            await self._redis.set(CATALOG_VERSION_KEY, 1, nx=True)
            return 1
        return int(raw)

    async def bump_version(self) -> int:
        return int(await self._redis.incr(CATALOG_VERSION_KEY))

    def list_key(
        self,
        version: int,
        page: int,
        page_size: int,
        show_reviews_count: bool,
        show_purchases_count: bool,
    ) -> str:
        flags = f"{int(show_reviews_count)}{int(show_purchases_count)}"
        return f"catalog:list:v{version}:{page}:{page_size}:{flags}"

    def detail_key(
        self,
        version: int,
        slug: str,
        show_reviews_count: bool,
        show_purchases_count: bool,
    ) -> str:
        flags = f"{int(show_reviews_count)}{int(show_purchases_count)}"
        return f"catalog:detail:v{version}:{slug}:{flags}"

    def reviews_key(self, version: int, slug: str, page: int, page_size: int) -> str:
        return f"catalog:reviews:v{version}:{slug}:{page}:{page_size}"

    async def get_response(self, key: str) -> str | None:
        value = await self._redis.get(key)
        return value if isinstance(value, str) else None

    async def set_response(self, key: str, body: str) -> None:
        await self._redis.set(key, body, ex=RESPONSE_CACHE_TTL_SECONDS)

    def counter_key(self, counter: CounterName, ebook_id: UUID) -> str:
        return f"catalog:counter:{counter}:{ebook_id}"

    async def get_counter(self, counter: CounterName, ebook_id: UUID) -> int | None:
        raw = await self._redis.get(self.counter_key(counter, ebook_id))
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    async def get_many_counters(
        self,
        counter: CounterName,
        ebook_ids: list[UUID],
    ) -> dict[UUID, int]:
        if not ebook_ids:
            return {}
        keys = [self.counter_key(counter, ebook_id) for ebook_id in ebook_ids]
        values = await self._redis.mget(keys)
        cached: dict[UUID, int] = {}
        for ebook_id, raw in zip(ebook_ids, values, strict=True):
            if raw is None:
                continue
            try:
                cached[ebook_id] = int(raw)
            except ValueError:
                continue
        return cached

    async def set_counter(
        self,
        counter: CounterName,
        ebook_id: UUID,
        value: int,
    ) -> None:
        await self._redis.set(
            self.counter_key(counter, ebook_id),
            value,
            ex=COUNTER_CACHE_TTL_SECONDS,
        )

    async def set_many_counters(
        self,
        counter: CounterName,
        values: dict[UUID, int],
    ) -> None:
        if not values:
            return
        pipeline = self._redis.pipeline()
        for ebook_id, value in values.items():
            pipeline.set(
                self.counter_key(counter, ebook_id),
                value,
                ex=COUNTER_CACHE_TTL_SECONDS,
            )
        await pipeline.execute()

    async def invalidate_counters(self, ebook_id: UUID) -> None:
        await self._redis.delete(
            self.counter_key("reviews", ebook_id),
            self.counter_key("purchases", ebook_id),
        )
