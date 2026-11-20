import pytest
from app.core.deps import get_health_service
from app.schemas.health import DependencyStatus, HealthResponse, HealthStatus
from fastapi import FastAPI
from httpx import AsyncClient


class StaticHealthService:
    def __init__(self, response: HealthResponse) -> None:
        self._response = response

    async def check(self) -> HealthResponse:
        return self._response


def build_response(status: HealthStatus, database_healthy: bool) -> HealthResponse:
    return HealthResponse(
        status=status,
        env="test",
        version="0.1.0",
        dependencies={
            "database": DependencyStatus(healthy=database_healthy, latency_ms=1.25, error=None),
            "redis": DependencyStatus(healthy=True, latency_ms=0.75, error=None),
        },
    )


@pytest.fixture
def healthy_response() -> HealthResponse:
    return build_response(HealthStatus.OK, database_healthy=True)


@pytest.fixture
def degraded_response() -> HealthResponse:
    return build_response(HealthStatus.DEGRADED, database_healthy=False)


async def test_health_returns_ok(
    app: FastAPI, client: AsyncClient, healthy_response: HealthResponse
) -> None:
    app.dependency_overrides[get_health_service] = lambda: StaticHealthService(healthy_response)

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "test"
    assert body["dependencies"]["database"]["healthy"] is True
    assert body["dependencies"]["redis"]["healthy"] is True


async def test_health_returns_503_when_dependency_is_down(
    app: FastAPI, client: AsyncClient, degraded_response: HealthResponse
) -> None:
    app.dependency_overrides[get_health_service] = lambda: StaticHealthService(degraded_response)

    response = await client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"]["healthy"] is False
