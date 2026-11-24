import asyncio
import time
from collections.abc import Awaitable, Callable

from app import __version__
from app.core.config import get_settings
from app.repositories.health import HealthRepository
from app.schemas.health import DependencyStatus, HealthResponse, HealthStatus

PROBE_TIMEOUT_SECONDS = 3.0


class HealthService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    async def check(self) -> HealthResponse:
        database, redis = await asyncio.gather(
            self._measure("database", self._repository.check_database),
            self._measure("redis", self._repository.check_redis),
        )
        dependencies = {"database": database, "redis": redis}
        all_healthy = all(dependency.healthy for dependency in dependencies.values())
        settings = get_settings()
        return HealthResponse(
            status=HealthStatus.OK if all_healthy else HealthStatus.DEGRADED,
            env=settings.ENV,
            version=__version__,
            dependencies=dependencies,
        )

    async def _measure(self, name: str, probe: Callable[[], Awaitable[None]]) -> DependencyStatus:
        started_at = time.perf_counter()
        try:
            await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return DependencyStatus(
                healthy=False,
                latency_ms=latency_ms,
                error=f"{name}: {type(exc).__name__}",
            )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return DependencyStatus(healthy=True, latency_ms=latency_ms)
