from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from reactor_backend.api.exception_handlers import install_exception_handlers
from reactor_backend.api.middleware import RequestContextMiddleware
from reactor_backend.api.routers.health import router as health_router
from reactor_backend.config import Settings, get_settings
from reactor_backend.infrastructure.database import Database, DatabaseProtocol
from reactor_backend.logging import configure_logging

DatabaseFactory = Callable[[Settings], DatabaseProtocol]


def create_app(
    settings: Settings | None = None,
    database_factory: DatabaseFactory = Database,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = database_factory(resolved_settings)
        app.state.database = database
        await database.start()
        try:
            yield
        finally:
            await database.close()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if resolved_settings.environment == "prod" else "/docs",
        redoc_url=None,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestContextMiddleware)
    install_exception_handlers(application)
    application.include_router(health_router)
    return application


app = create_app()
