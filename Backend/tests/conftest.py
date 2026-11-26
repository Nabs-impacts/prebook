import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

os.environ.setdefault("ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-characters")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://prebook:prebook@localhost:5432/prebook_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

from app.core.deps import (
    get_admin_service,
    get_auth_service,
    get_ebook_service,
    get_order_service,
    get_settings_service,
    get_video_service,
)
from app.main import create_app
from app.repositories.admin import AdminRepository
from app.repositories.catalog_cache import CatalogCacheRepository
from app.repositories.ebook import EbookRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.repositories.order import OrderRepository
from app.repositories.order_rate_limit import OrderRateLimitRepository
from app.repositories.payment_state import PaymentStateRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_rate_limit import ReviewRateLimitRepository
from app.repositories.settings import SettingsRepository
from app.repositories.token import TokenRepository
from app.repositories.video import VideoRepository
from app.schemas.settings import SiteSettings
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.ebook import EbookService
from app.services.order import OrderService
from app.services.payment_provider import (
    FakePaymentProvider,
    IPayMoneyProvider,
    PaymentProviderRegistry,
)
from app.services.settings import SettingsService
from app.services.storage import LocalStorageBackend
from app.services.video import VideoService
from app.services.video_provider import ExternalUrlProvider

from tests.support import InMemoryAdminRepository, InMemorySettingsRepository
from tests.support_catalog import (
    InMemoryEbookRepository,
    InMemoryOrderRepository,
    InMemoryReviewRepository,
)
from tests.support_order import FakeTaskQueue
from tests.support_video import FakeCloudflareStreamProvider, InMemoryVideoRepository

TEST_WEBHOOK_SECRET = "test-webhook-secret"
TEST_FAKE_WEBHOOK_SECRET = "test-fake-payment-secret"


async def default_maintenance_settings() -> SiteSettings:
    return SiteSettings()


@pytest.fixture
def app() -> FastAPI:
    application = create_app()
    application.state.maintenance_settings_provider = default_maintenance_settings
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
def repository() -> InMemoryAdminRepository:
    return InMemoryAdminRepository()


@pytest.fixture
def settings_repository() -> InMemorySettingsRepository:
    return InMemorySettingsRepository()


@pytest.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    redis = FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest.fixture
async def auth_client(
    app: FastAPI,
    repository: InMemoryAdminRepository,
    fake_redis: FakeRedis,
) -> AsyncIterator[AsyncClient]:
    admin_repository = cast(AdminRepository, repository)
    token_repository = TokenRepository(cast(Redis, fake_redis))
    login_attempt_repository = LoginAttemptRepository(cast(Redis, fake_redis))

    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        admin_repository,
        token_repository,
        login_attempt_repository,
    )
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        admin_repository,
        token_repository,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
async def settings_client(
    app: FastAPI,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
) -> AsyncIterator[AsyncClient]:
    admin_repository = cast(AdminRepository, repository)
    token_repository = TokenRepository(cast(Redis, fake_redis))
    login_attempt_repository = LoginAttemptRepository(cast(Redis, fake_redis))
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        admin_repository,
    )

    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        admin_repository,
        token_repository,
        login_attempt_repository,
    )
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        admin_repository,
        token_repository,
    )
    app.dependency_overrides[get_settings_service] = lambda: settings_service
    app.state.maintenance_settings_provider = settings_service.get_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.maintenance_settings_provider = default_maintenance_settings


@pytest.fixture
def review_repository() -> InMemoryReviewRepository:
    return InMemoryReviewRepository()


@pytest.fixture
def ebook_repository(
    review_repository: InMemoryReviewRepository,
) -> InMemoryEbookRepository:
    repository = InMemoryEbookRepository(review_repository)
    review_repository.ebook_lookup = lambda ebook_id: repository.ebooks.get(ebook_id)
    return repository


@pytest.fixture
def video_repository(
    ebook_repository: InMemoryEbookRepository,
) -> InMemoryVideoRepository:
    return InMemoryVideoRepository(lambda ebook_id: ebook_repository.ebooks.get(ebook_id))


@pytest.fixture
def cloudflare_provider() -> FakeCloudflareStreamProvider:
    return FakeCloudflareStreamProvider()


@pytest.fixture
def external_provider() -> ExternalUrlProvider:
    return ExternalUrlProvider()


@pytest.fixture
def order_repository(
    ebook_repository: InMemoryEbookRepository,
) -> InMemoryOrderRepository:
    return InMemoryOrderRepository(lambda ebook_id: ebook_repository.ebooks.get(ebook_id))


@pytest.fixture
def fake_payment_provider() -> FakePaymentProvider:
    return FakePaymentProvider(webhook_secret=TEST_FAKE_WEBHOOK_SECRET)


@pytest.fixture
def payment_registry(
    fake_payment_provider: FakePaymentProvider,
) -> PaymentProviderRegistry:
    return PaymentProviderRegistry(
        {
            "fake": fake_payment_provider,
            "ipay_money": IPayMoneyProvider(
                "sk_test",
                "ipay-webhook-secret",
                "https://frontend.test",
                "sandbox",
                "https://i-pay.money/api/v1",
            ),
        }
    )


@pytest.fixture
def fake_task_queue() -> FakeTaskQueue:
    return FakeTaskQueue()


@pytest.fixture
def order_service(
    order_repository: InMemoryOrderRepository,
    ebook_repository: InMemoryEbookRepository,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
    payment_registry: PaymentProviderRegistry,
    fake_task_queue: FakeTaskQueue,
) -> OrderService:
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        cast(AdminRepository, repository),
    )
    return OrderService(
        cast(OrderRepository, order_repository),
        cast(EbookRepository, ebook_repository),
        settings_service,
        payment_registry,
        OrderRateLimitRepository(cast(Redis, fake_redis)),
        CatalogCacheRepository(cast(Redis, fake_redis)),
        fake_task_queue,
        cast(AdminRepository, repository),
        PaymentStateRepository(cast(Redis, fake_redis)),
        provider_code="fake",
        rate_limit_attempts=5,
        rate_limit_window_seconds=60,
        reconciliation_max_age_minutes=120,
        reconciliation_interval_minutes=2,
        reconciliation_max_interval_minutes=30,
        task_batch_size=100,
    )


@pytest.fixture
async def order_client(
    app: FastAPI,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
    order_service: OrderService,
) -> AsyncIterator[AsyncClient]:
    admin_repository = cast(AdminRepository, repository)
    token_repository = TokenRepository(cast(Redis, fake_redis))
    login_attempt_repository = LoginAttemptRepository(cast(Redis, fake_redis))
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        admin_repository,
    )

    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        admin_repository,
        token_repository,
        login_attempt_repository,
    )
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        admin_repository,
        token_repository,
    )
    app.dependency_overrides[get_settings_service] = lambda: settings_service
    app.dependency_overrides[get_order_service] = lambda: order_service
    app.state.maintenance_settings_provider = settings_service.get_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.maintenance_settings_provider = default_maintenance_settings


@pytest.fixture
def storage_backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(
        private_dir=tmp_path / "private",
        public_dir=tmp_path / "public",
        public_url="/media",
    )


@pytest.fixture
async def catalog_service(
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
    ebook_repository: InMemoryEbookRepository,
    review_repository: InMemoryReviewRepository,
    order_repository: InMemoryOrderRepository,
    storage_backend: LocalStorageBackend,
    video_repository: InMemoryVideoRepository,
) -> EbookService:
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        cast(AdminRepository, repository),
    )
    return EbookService(
        cast(EbookRepository, ebook_repository),
        cast(ReviewRepository, review_repository),
        cast(OrderRepository, order_repository),
        CatalogCacheRepository(cast(Redis, fake_redis)),
        ReviewRateLimitRepository(cast(Redis, fake_redis)),
        settings_service,
        storage_backend,
        cast(VideoRepository, video_repository),
    )


@pytest.fixture
def video_service(
    ebook_repository: InMemoryEbookRepository,
    video_repository: InMemoryVideoRepository,
    fake_redis: FakeRedis,
    cloudflare_provider: FakeCloudflareStreamProvider,
    external_provider: ExternalUrlProvider,
) -> VideoService:
    return VideoService(
        cast(VideoRepository, video_repository),
        cast(EbookRepository, ebook_repository),
        CatalogCacheRepository(cast(Redis, fake_redis)),
        cloudflare_provider,
        external_provider,
        max_duration_seconds=600,
        max_size_bytes=500 * 1024 * 1024,
        webhook_secret=TEST_WEBHOOK_SECRET,
    )


@pytest.fixture
async def catalog_client(
    app: FastAPI,
    repository: InMemoryAdminRepository,
    settings_repository: InMemorySettingsRepository,
    fake_redis: FakeRedis,
    catalog_service: EbookService,
    video_service: VideoService,
) -> AsyncIterator[AsyncClient]:
    admin_repository = cast(AdminRepository, repository)
    token_repository = TokenRepository(cast(Redis, fake_redis))
    login_attempt_repository = LoginAttemptRepository(cast(Redis, fake_redis))
    settings_service = SettingsService(
        cast(SettingsRepository, settings_repository),
        admin_repository,
    )

    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        admin_repository,
        token_repository,
        login_attempt_repository,
    )
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        admin_repository,
        token_repository,
    )
    app.dependency_overrides[get_settings_service] = lambda: settings_service
    app.dependency_overrides[get_ebook_service] = lambda: catalog_service
    app.dependency_overrides[get_video_service] = lambda: video_service
    app.state.maintenance_settings_provider = settings_service.get_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.maintenance_settings_provider = default_maintenance_settings
