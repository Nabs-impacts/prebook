from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from redis.asyncio import Redis

from app.core.security import hash_token

REFRESH_KEY_PREFIX = "auth:refresh"
REFRESH_USER_KEY_PREFIX = "auth:refresh:user"
REVOKED_ACCESS_KEY_PREFIX = "auth:access:revoked"


class TokenRepository:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _refresh_key(self, token: str) -> str:
        return f"{REFRESH_KEY_PREFIX}:{hash_token(token)}"

    def _refresh_user_key(self, user_id: UUID) -> str:
        return f"{REFRESH_USER_KEY_PREFIX}:{user_id}"

    def _revoked_access_key(self, jti: str) -> str:
        return f"{REVOKED_ACCESS_KEY_PREFIX}:{jti}"

    async def store_refresh(self, user_id: UUID, token: str, expires_at: datetime) -> None:
        ttl_seconds = max(int((expires_at - datetime.now(UTC)).total_seconds()), 1)
        token_hash = hash_token(token)
        user_key = self._refresh_user_key(user_id)
        await self._redis.set(self._refresh_key(token), str(user_id), ex=ttl_seconds)
        await cast(Awaitable[int], self._redis.sadd(user_key, token_hash))
        await self._redis.expire(user_key, ttl_seconds)

    async def consume_refresh(self, token: str) -> UUID | None:
        token_hash = hash_token(token)
        value = await self._redis.getdel(f"{REFRESH_KEY_PREFIX}:{token_hash}")
        if value is None:
            return None
        await cast(
            Awaitable[int],
            self._redis.srem(self._refresh_user_key(UUID(str(value))), token_hash),
        )
        return UUID(str(value))

    async def revoke_refresh(self, token: str) -> None:
        token_hash = hash_token(token)
        value = await self._redis.getdel(f"{REFRESH_KEY_PREFIX}:{token_hash}")
        if value is not None:
            await cast(
                Awaitable[int],
                self._redis.srem(self._refresh_user_key(UUID(str(value))), token_hash),
            )

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        user_key = self._refresh_user_key(user_id)
        token_hashes = await cast(Awaitable[set[str]], self._redis.smembers(user_key))
        if token_hashes:
            await self._redis.delete(*(f"{REFRESH_KEY_PREFIX}:{value}" for value in token_hashes))
        await self._redis.delete(user_key)

    async def revoke_access(self, jti: str, expires_at: datetime) -> None:
        ttl_seconds = max(int((expires_at - datetime.now(UTC)).total_seconds()), 1)
        await self._redis.set(self._revoked_access_key(jti), "1", ex=ttl_seconds)

    async def is_access_revoked(self, jti: str) -> bool:
        return bool(await self._redis.exists(self._revoked_access_key(jti)))
