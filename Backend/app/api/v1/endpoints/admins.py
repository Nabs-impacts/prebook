from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app.core.deps import AdminServiceDep, RequireSuperAdminDep
from app.core.request import client_ip
from app.schemas.admin import AdminCreate, AdminListResponse, AdminRead, AdminUpdate

router = APIRouter(prefix="/admin/admins")


@router.get("", response_model=AdminListResponse)
async def list_admins(
    service: AdminServiceDep,
    _: RequireSuperAdminDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminListResponse:
    return await service.list_admins(page, page_size)


@router.post("", response_model=AdminRead, status_code=status.HTTP_201_CREATED)
async def create_admin(
    payload: AdminCreate,
    request: Request,
    actor: RequireSuperAdminDep,
    service: AdminServiceDep,
) -> AdminRead:
    return await service.create_admin(actor, payload, client_ip(request))


@router.patch("/{admin_id}", response_model=AdminRead)
async def update_admin(
    admin_id: UUID,
    payload: AdminUpdate,
    request: Request,
    actor: RequireSuperAdminDep,
    service: AdminServiceDep,
) -> AdminRead:
    return await service.update_admin(actor, admin_id, payload, client_ip(request))


@router.delete("/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin(
    admin_id: UUID,
    request: Request,
    actor: RequireSuperAdminDep,
    service: AdminServiceDep,
) -> None:
    await service.delete_admin(actor, admin_id, client_ip(request))
