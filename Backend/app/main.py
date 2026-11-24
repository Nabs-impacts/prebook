from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.maintenance import MaintenanceMiddleware
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from app.db.session import close_redis, dispose_engine
from app.services.settings import load_maintenance_settings
from app.services.storage import get_storage_backend


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await close_redis()
        await dispose_engine()

    is_production = settings.ENV == "production"
    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/openapi.json",
    )

    app.state.maintenance_settings_provider = load_maintenance_settings
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(MaintenanceMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ORIGINS != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    get_storage_backend()
    app.mount(
        settings.STORAGE_PUBLIC_URL,
        StaticFiles(directory=settings.storage_public_dir),
        name="media",
    )
    return app


app = create_app()
