import hashlib

from redis.asyncio import Redis

LOGIN_ATTEMPT_KEY_PREFIX = "auth:login"


class LoginAttemptRepository:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, ip: str, email: str) -> str:
        identity = f"{ip}:{email.strip().lower()}".encode()
        digest = hashlib.sha256(identity).hexdigest()
        return f"{LOGIN_ATTEMPT_KEY_PREFIX}:{digest}"

    async def increment(self, ip: str, email: str, window_seconds: int) -> int:
        key = self._key(ip, email)
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.expire(key, window_seconds)
        return count

    async def reset(self, ip: str, email: str) -> None:
        await self._redis.delete(self._key(ip, email))
