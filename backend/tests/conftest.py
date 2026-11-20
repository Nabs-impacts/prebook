import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-characters")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://prebook:prebook@localhost:5432/prebook_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
