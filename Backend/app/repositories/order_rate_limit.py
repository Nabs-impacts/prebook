import hashlib

from redis.asyncio import Redis

ORDER_RATE_LIMIT_KEY_PREFIX = "orders:rate"


class OrderRateLimitRepository:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, ip: str) -> str:
        digest = hashlib.sha256(ip.encode("utf-8")).hexdigest()
        return f"{ORDER_RATE_LIMIT_KEY_PREFIX}:{digest}"

    async def hit(self, ip: str, window_seconds: int) -> int:
        key = self._key(ip)
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.expire(key, window_seconds)
        return count
