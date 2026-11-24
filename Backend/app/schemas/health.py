from enum import StrEnum

from pydantic import BaseModel, Field


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class DependencyStatus(BaseModel):
    healthy: bool
    latency_ms: float = Field(ge=0)
    error: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    env: str
    version: str
    dependencies: dict[str, DependencyStatus]
