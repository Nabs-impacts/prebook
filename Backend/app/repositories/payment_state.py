import hashlib
import json
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

WEBHOOK_EVENT_TTL_SECONDS = 7 * 24 * 3600
RECONCILIATION_TTL_SECONDS = 3 * 3600


class PaymentStateRepository:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def claim_webhook_event(self, reference: str, status: str) -> bool:
        digest = hashlib.sha256(f"{reference}:{status}".encode()).hexdigest()
        claimed = await self._redis.set(
            f"payment:webhook:{digest}",
            "1",
            nx=True,
            ex=WEBHOOK_EVENT_TTL_SECONDS,
        )
        return bool(claimed)

    async def reconciliation_due(
        self,
        order_id: UUID,
        now: datetime,
        base_minutes: int,
        max_minutes: int,
    ) -> bool:
        raw = await self._redis.get(f"payment:reconcile:{order_id}")
        if raw is None:
            return True
        attempts = self._attempts(raw)
        interval = min(base_minutes * (2 ** max(attempts - 1, 0)), max_minutes)
        last = self._last_check(raw)
        return bool(now.timestamp() >= last + interval * 60)

    async def record_reconciliation(self, order_id: UUID, now: datetime) -> None:
        key = f"payment:reconcile:{order_id}"
        raw = await self._redis.get(key)
        attempts = self._attempts(raw) if raw is not None else 0
        payload = {"last": now.timestamp(), "attempts": attempts + 1}
        await self._redis.set(key, json.dumps(payload), ex=RECONCILIATION_TTL_SECONDS)

    def _attempts(self, raw: str) -> int:
        payload = self._payload(raw)
        attempts = payload.get("attempts", 1)
        return int(attempts) if isinstance(attempts, int) and attempts > 0 else 1

    def _last_check(self, raw: str) -> float:
        payload = self._payload(raw)
        last = payload.get("last", 0.0)
        return float(last) if isinstance(last, (int, float)) else 0.0

    def _payload(self, raw: str) -> dict[str, object]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload
