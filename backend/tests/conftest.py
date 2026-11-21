import os
from collections.abc import AsyncIterator
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

from app.core.deps import get_admin_service, get_auth_service
from app.main import create_app
from app.repositories.admin import AdminRepository
from app.repositories.login_attempt import LoginAttemptRepository
from app.repositories.token import TokenRepository
from app.services.admin import AdminService
from app.services.auth import AuthService

from tests.support import InMemoryAdminRepository


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
def repository() -> InMemoryAdminRepository:
    return InMemoryAdminRepository()


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
