"""Connection provider seam.

``DatabaseProtocol`` stays ``{start, ping, close}`` so ``tests/unit/test_health.py``
fakes keep working. Business SQL goes through :class:`ConnectionProvider`, which
the concrete :class:`~reactor_backend.infrastructure.database.engine.Database`
implements.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class ConnectionProvider(Protocol):
    def engine(self) -> AsyncEngine | None: ...

    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]: ...


class MissingEngineError(RuntimeError):
    """Raised when business SQL is attempted without a started engine."""


@asynccontextmanager
async def connect(engine: AsyncEngine | None) -> AsyncIterator[AsyncConnection]:
    if engine is None:
        raise MissingEngineError("database engine is not started")
    async with engine.connect() as connection:
        yield connection
