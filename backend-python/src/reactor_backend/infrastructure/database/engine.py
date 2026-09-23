from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from reactor_backend.config import Settings


class DatabaseProtocol(Protocol):
    async def start(self) -> None: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class Database:
    """Connection factory + lifecycle. ``DatabaseProtocol`` is intentionally not
    extended: ``tests/unit/test_health.py::FakeDatabase`` depends on its shape."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None

    async def start(self) -> None:
        if self._engine is not None:
            return
        self._engine = create_async_engine(
            self._settings.sqlalchemy_database_url,
            pool_pre_ping=True,
            pool_size=self._settings.mysql_pool_size,
            max_overflow=self._settings.mysql_max_overflow,
            pool_recycle=self._settings.mysql_pool_recycle_seconds,
            connect_args={"connect_timeout": self._settings.database_ready_timeout_seconds},
        )

    async def ping(self) -> None:
        if self._engine is None:
            raise RuntimeError("database engine is not started")
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    def engine(self) -> AsyncEngine | None:
        return self._engine

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        if self._engine is None:
            raise RuntimeError("database engine is not started")
        async with self._engine.connect() as connection:
            yield connection

    async def close(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
