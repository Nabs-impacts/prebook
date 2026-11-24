from fastapi import APIRouter, Request, status

from app.core.deps import AuthServiceDep, OptionalAccessTokenDep, RequireAdminDep
from app.core.request import client_ip
from app.schemas.admin import AdminRead
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    service: AuthServiceDep,
) -> TokenResponse:
    return await service.login(str(payload.email), payload.password, client_ip(request))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, service: AuthServiceDep) -> TokenResponse:
    return await service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    service: AuthServiceDep,
    access_token: OptionalAccessTokenDep,
    payload: LogoutRequest | None = None,
) -> None:
    await service.logout(payload.refresh_token if payload else None, access_token)


@router.get("/me", response_model=AdminRead)
async def me(user: RequireAdminDep) -> AdminRead:
    return AdminRead.model_validate(user)
