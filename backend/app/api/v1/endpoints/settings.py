import hashlib

from fastapi import APIRouter, Request, Response

from app.core.deps import RequireAdminDep, SettingsServiceDep
from app.core.request import client_ip
from app.schemas.settings import SiteSettings, SiteSettingsUpdate

PUBLIC_CACHE_CONTROL = "public, max-age=30"

public_router = APIRouter(prefix="/public/settings")
admin_router = APIRouter(prefix="/admin/settings")


def build_etag(body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f'"{digest}"'


@public_router.get("", response_model=SiteSettings)
async def read_public_settings(request: Request, service: SettingsServiceDep) -> Response:
    settings = await service.get_settings()
    body = settings.model_dump_json()
    etag = build_etag(body)
    headers = {"Cache-Control": PUBLIC_CACHE_CONTROL, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


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
