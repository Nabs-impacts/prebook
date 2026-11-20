from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from app.db.session import close_redis, dispose_engine


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

    app.add_middleware(RequestLoggingMiddleware)
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
    return app


app = create_app()
