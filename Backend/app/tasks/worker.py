from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.tasks.orders import expire_pending_orders, fulfill_order, reconcile_pending_orders


async def healthcheck_task(ctx: dict[str, Any]) -> str:
    return "ok"


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().LOG_LEVEL)


async def shutdown(ctx: dict[str, Any]) -> None:
    return None


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        healthcheck_task,
        fulfill_order,
        expire_pending_orders,
        reconcile_pending_orders,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(expire_pending_orders, minute=set(range(60))),
        cron(reconcile_pending_orders, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings: RedisSettings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    job_timeout = 300
    max_jobs = 10
    keep_result = 3600
