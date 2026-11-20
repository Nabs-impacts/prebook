from fastapi import APIRouter, Response, status

from app.core.deps import HealthServiceDep
from app.schemas.health import HealthResponse, HealthStatus

router = APIRouter(prefix="/health")


@router.get("", response_model=HealthResponse)
async def read_health(response: Response, service: HealthServiceDep) -> HealthResponse:
    health = await service.check()
    if health.status is not HealthStatus.OK:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health
