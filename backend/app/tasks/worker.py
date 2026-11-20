from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging


async def healthcheck_task(ctx: dict[str, Any]) -> str:
    return "ok"


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().LOG_LEVEL)


async def shutdown(ctx: dict[str, Any]) -> None:
    return None


class WorkerSettings:
    functions: ClassVar[list[Any]] = [healthcheck_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings: RedisSettings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    job_timeout = 300
    max_jobs = 10
    keep_result = 3600
