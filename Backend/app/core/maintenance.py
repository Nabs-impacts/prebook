import logging
from collections.abc import Awaitable, Callable
from typing import cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import current_request_id, error_payload
from app.schemas.settings import SiteSettings

logger = logging.getLogger("prebook.maintenance")

RETRY_AFTER_SECONDS = "3600"
EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/v1/auth",
    "/api/v1/admin",
    "/api/v1/public/settings",
    "/api/v1/webhooks",
)

SettingsProvider = Callable[[], Awaitable[SiteSettings]]


def is_exempt(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in EXEMPT_PREFIXES)


class MaintenanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if is_exempt(request.url.path):
            return await call_next(request)

        provider = cast(
            SettingsProvider | None,
            getattr(request.app.state, "maintenance_settings_provider", None),
        )
        if provider is None:
            return await call_next(request)

        try:
            settings = await provider()
        except Exception:
            logger.exception("maintenance_settings_unavailable")
            return await call_next(request)

        if not settings.maintenance_mode:
            return await call_next(request)

        return JSONResponse(
            status_code=503,
            content=error_payload(
                "maintenance",
                settings.maintenance_message,
                current_request_id(request),
            ),
            headers={
                "Retry-After": RETRY_AFTER_SECONDS,
                "Cache-Control": "no-store",
            },
        )
