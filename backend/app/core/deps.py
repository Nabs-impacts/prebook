from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.db.session import get_redis_client, get_session
from app.models.user import User
from app.repositories.admin import AdminRepository
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.health import HealthRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.repositories.order import OrderRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_rate_limit import ReviewRateLimitRepository
from app.repositories.settings import SettingsRepository
from app.repositories.token import TokenRepository
from app.repositories.video import VideoRepository
from app.services.admin import AdminService
from app.services.auth import AuthService, ensure_admin, ensure_super_admin
from app.services.ebook import EbookService
from app.services.health import HealthService
from app.services.settings import SettingsService
from app.services.storage import StorageBackend, get_storage_backend
from app.services.video import VideoService
from app.services.video_provider import CloudflareStreamProvider, ExternalUrlProvider

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


def get_ebook_repository(session: DbSession) -> EbookRepository:
    return EbookRepository(session)


def get_video_repository(session: DbSession) -> VideoRepository:
    return VideoRepository(session)


def get_review_repository(session: DbSession) -> ReviewRepository:
    return ReviewRepository(session)


def get_order_repository(session: DbSession) -> OrderRepository:
    return OrderRepository(session)


def get_catalog_cache_repository(redis: RedisClient) -> CatalogCacheRepository:
    return CatalogCacheRepository(redis)


def get_review_rate_limit_repository(redis: RedisClient) -> ReviewRateLimitRepository:
    return ReviewRateLimitRepository(redis)


def get_ebook_service(
    ebook_repository: Annotated[EbookRepository, Depends(get_ebook_repository)],
    review_repository: Annotated[ReviewRepository, Depends(get_review_repository)],
    order_repository: Annotated[OrderRepository, Depends(get_order_repository)],
    cache_repository: Annotated[CatalogCacheRepository, Depends(get_catalog_cache_repository)],
    rate_limit_repository: Annotated[
        ReviewRateLimitRepository, Depends(get_review_rate_limit_repository)
    ],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
    storage_backend: Annotated[StorageBackend, Depends(get_storage_backend)],
    video_repository: Annotated[VideoRepository, Depends(get_video_repository)],
) -> EbookService:
    return EbookService(
        ebook_repository,
        review_repository,
        order_repository,
        cache_repository,
        rate_limit_repository,
        settings_service,
        storage_backend,
        video_repository,
    )


def get_cloudflare_stream_provider() -> CloudflareStreamProvider:
    settings = get_settings()
    return CloudflareStreamProvider(
        settings.CLOUDFLARE_ACCOUNT_ID or "",
        settings.CLOUDFLARE_STREAM_API_TOKEN or "",
    )


def get_external_url_provider() -> ExternalUrlProvider:
    return ExternalUrlProvider()


def get_video_service(
    video_repository: Annotated[VideoRepository, Depends(get_video_repository)],
    ebook_repository: Annotated[EbookRepository, Depends(get_ebook_repository)],
    cache_repository: Annotated[CatalogCacheRepository, Depends(get_catalog_cache_repository)],
    cloudflare_provider: Annotated[
        CloudflareStreamProvider, Depends(get_cloudflare_stream_provider)
    ],
    external_provider: Annotated[ExternalUrlProvider, Depends(get_external_url_provider)],
) -> VideoService:
    settings = get_settings()
    return VideoService(
        video_repository,
        ebook_repository,
        cache_repository,
        cloudflare_provider,
        external_provider,
        max_duration_seconds=settings.VIDEO_MAX_DURATION_SECONDS,
        max_size_bytes=settings.VIDEO_MAX_SIZE_BYTES,
        webhook_secret=settings.CLOUDFLARE_STREAM_WEBHOOK_SECRET,
    )


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
EbookServiceDep = Annotated[EbookService, Depends(get_ebook_service)]
VideoServiceDep = Annotated[VideoService, Depends(get_video_service)]
RequireAdminDep = Annotated[User, Depends(require_admin)]
RequireSuperAdminDep = Annotated[User, Depends(require_super_admin)]
OptionalAccessTokenDep = Annotated[str | None, Depends(get_optional_access_token)]
