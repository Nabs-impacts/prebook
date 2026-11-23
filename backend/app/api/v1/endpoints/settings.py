from fastapi import APIRouter, Request, Response

from app.core.deps import RequireAdminDep, SettingsServiceDep
from app.core.http import conditional_json_response
from app.core.request import client_ip
from app.schemas.settings import SiteSettings, SiteSettingsUpdate

PUBLIC_CACHE_CONTROL = "public, max-age=30"

public_router = APIRouter(prefix="/public/settings")
admin_router = APIRouter(prefix="/admin/settings")


@public_router.get("", response_model=SiteSettings)
async def read_public_settings(request: Request, service: SettingsServiceDep) -> Response:
    settings = await service.get_settings()
    return conditional_json_response(
        request,
        settings.model_dump_json(),
        PUBLIC_CACHE_CONTROL,
    )


@admin_router.get("", response_model=SiteSettings)
async def read_admin_settings(
    _: RequireAdminDep,
    service: SettingsServiceDep,
) -> SiteSettings:
    return await service.get_settings()


@admin_router.patch("", response_model=SiteSettings)
async def update_admin_settings(
    payload: SiteSettingsUpdate,
    request: Request,
    actor: RequireAdminDep,
    service: SettingsServiceDep,
) -> SiteSettings:
    return await service.update_settings(actor, payload, client_ip(request))
