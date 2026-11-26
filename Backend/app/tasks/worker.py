from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.tasks.orders import fulfill_order, reconcile_payment_orders


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
        reconcile_payment_orders,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(reconcile_payment_orders, minute=set(range(0, 60, 2))),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings: RedisSettings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    job_timeout = 300
    max_jobs = 10
    keep_result = 3600
