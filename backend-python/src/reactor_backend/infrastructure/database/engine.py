from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from asyncmy.constants import CLIENT
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
            connect_args={
                "connect_timeout": self._settings.database_ready_timeout_seconds,
                # MySQL Connector/J sets CLIENT_FOUND_ROWS by default
                # (``useAffectedRows=false``), so Java's ``dao.upsert(po) > 0`` /
                # ``dao.updateStatus(...) > 0`` count *found* rows. asyncmy leaves
                # the flag off and would count *changed* rows — a matched-but-unchanged
                # UPDATE (or a no-op ON DUPLICATE KEY UPDATE) would then report 0 and
                # flip the boolean Java returns as ``true``. asyncmy ORs this into its
                # own CAPABILITIES set, so passing it here is additive (connection.pyx:
                # ``client_flag |= CAPABILITIES``).
                "client_flag": CLIENT.FOUND_ROWS,
            },
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
        """One auto-commit unit of work, matching Java's per-mapper-call model.

        ``engine.begin()`` (not ``engine.connect()``) is load-bearing. SQLAlchemy
        2.0's ``connect()`` is *commit-as-you-go*: closing a connection that never
        called ``commit()`` **rolls back**, so every write this repository has
        ever issued through ``connect()`` vanished on exit. Measured 2026-09-24
        against the throwaway mysqld: an INSERT through ``connect()`` is gone
        immediately afterwards, the same INSERT through ``begin()`` persists.

        Java's ``FeaturedConversationAdminApplicationService`` has no
        ``@Transactional``, so each mapper call is its own auto-commit statement
        — which is exactly one ``connect()`` block per repository method here.
        Keep that one-call-per-block shape: two writes inside one block would
        become atomic under ``begin()`` and drift from Java's semantics.
        """
        if self._engine is None:
            raise RuntimeError("database engine is not started")
        async with self._engine.begin() as connection:
            yield connection

    async def close(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
