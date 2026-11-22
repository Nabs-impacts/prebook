from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.session import get_redis_client, get_session
from app.models.user import User
from app.repositories.admin import AdminRepository
from app.repositories.health import HealthRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.repositories.settings import SettingsRepository
from app.repositories.token import TokenRepository
from app.services.admin import AdminService
from app.services.auth import AuthService, ensure_admin, ensure_super_admin
from app.services.health import HealthService
from app.services.settings import SettingsService

DbSession = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis_client)]

bearer_scheme = HTTPBearer(auto_error=False)


def get_health_service(session: DbSession, redis: RedisClient) -> HealthService:
    return HealthService(HealthRepository(session, redis))


def get_admin_repository(session: DbSession) -> AdminRepository:
    return AdminRepository(session)


def get_token_repository(redis: RedisClient) -> TokenRepository:
    return TokenRepository(redis)


def get_login_attempt_repository(redis: RedisClient) -> LoginAttemptRepository:
    return LoginAttemptRepository(redis)


def get_auth_service(
    admin_repository: Annotated[AdminRepository, Depends(get_admin_repository)],
    token_repository: Annotated[TokenRepository, Depends(get_token_repository)],
    login_attempt_repository: Annotated[
        LoginAttemptRepository, Depends(get_login_attempt_repository)
    ],
) -> AuthService:
    return AuthService(admin_repository, token_repository, login_attempt_repository)


def get_admin_service(
    admin_repository: Annotated[AdminRepository, Depends(get_admin_repository)],
    token_repository: Annotated[TokenRepository, Depends(get_token_repository)],
) -> AdminService:
    return AdminService(admin_repository, token_repository)


def get_settings_repository(session: DbSession, redis: RedisClient) -> SettingsRepository:
    return SettingsRepository(session, redis)


def get_settings_service(
    settings_repository: Annotated[SettingsRepository, Depends(get_settings_repository)],
    admin_repository: Annotated[AdminRepository, Depends(get_admin_repository)],
) -> SettingsService:
    return SettingsService(settings_repository, admin_repository)


def get_optional_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    return await service.current_user(credentials.credentials)


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    return ensure_admin(user)


async def require_super_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    return ensure_super_admin(user)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
RequireAdminDep = Annotated[User, Depends(require_admin)]
RequireSuperAdminDep = Annotated[User, Depends(require_super_admin)]
OptionalAccessTokenDep = Annotated[str | None, Depends(get_optional_access_token)]
