from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

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
        # Construction is I/O-free: health-only fakes (FakeDatabase) still boot.
        app.state.featured_query_use_case = _build_featured_use_case(database)
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
        # Java answers 404 on a trailing slash; Starlette's default 307 redirect
        # would change the status code and emit a Location header (R-30).
        redirect_slashes=False,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestContextMiddleware)
    install_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(_featured_router())
    return application


def _featured_router() -> Any:
    from reactor_backend.api.routers.featured_conversations import (
        router as featured_router,
    )

    return featured_router


def _build_featured_use_case(database: Any) -> Any:
    from reactor_backend.application.featured_conversation_query import (
        FeaturedConversationQueryUseCase,
    )
    from reactor_backend.domain.replay_projector import ReplayProjector
    from reactor_backend.infrastructure.llm_model_window import LlmModelWindowResolver
    from reactor_backend.infrastructure.repositories import (
        ExecutionLedgerRepository,
        FeaturedConversationRepository,
    )

    return FeaturedConversationQueryUseCase(
        featured_reader=FeaturedConversationRepository(database),
        ledger_reader=ExecutionLedgerRepository(database),
        model_window=LlmModelWindowResolver(database),
        history_projector=ReplayProjector(),
    )


app = create_app()
