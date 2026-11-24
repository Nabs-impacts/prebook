from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import get_settings
from app.db.session import get_redis_client, get_session_factory
from app.repositories.admin import AdminRepository
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.order import OrderRepository
from app.repositories.order_rate_limit import OrderRateLimitRepository
from app.repositories.settings import SettingsRepository
from app.services.order import OrderService
from app.services.payment_provider import get_payment_registry
from app.services.settings import SettingsService
from app.tasks.queue import ArqTaskQueue


@asynccontextmanager
async def order_service() -> AsyncIterator[OrderService]:
    settings = get_settings()
    redis = get_redis_client()
    async with get_session_factory()() as session:
        settings_service = SettingsService(
            SettingsRepository(session, redis),
            AdminRepository(session),
        )
        yield OrderService(
            OrderRepository(session),
            EbookRepository(session),
            settings_service,
            get_payment_registry(),
            OrderRateLimitRepository(redis),
            CatalogCacheRepository(redis),
            ArqTaskQueue(),
            payment_methods=settings.PAYMENT_METHOD_PROVIDERS,
            fake_payments_enabled=settings.fake_payments_enabled,
            rate_limit_attempts=settings.ORDER_RATE_LIMIT_ATTEMPTS,
            rate_limit_window_seconds=settings.ORDER_RATE_LIMIT_WINDOW_SECONDS,
            pending_expiration_minutes=settings.ORDER_PENDING_EXPIRATION_MINUTES,
            reconciliation_minutes=settings.ORDER_RECONCILIATION_MINUTES,
            task_batch_size=settings.ORDER_TASK_BATCH_SIZE,
        )


async def fulfill_order(ctx: dict[str, Any], order_id: str) -> None:
    return None


async def expire_pending_orders(ctx: dict[str, Any]) -> int:
    async with order_service() as service:
        return await service.expire_pending_orders()


async def reconcile_pending_orders(ctx: dict[str, Any]) -> int:
    async with order_service() as service:
        return await service.reconcile_pending_orders()
