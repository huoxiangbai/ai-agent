"""Model window resolver over ``ai_client_model``.

Port of the ``LlmModelCatalog.resolve(modelName).getMaxInputTokens()`` lookup used
by ``ConversationHistoryReplayService.resolveContextWindow``. Catalog failures
must never break history replay — callers fall back to 100_000.

The domain's history assembly is synchronous, so the catalog is read ahead of
time via :meth:`prefill`; :meth:`max_input_tokens` is then a pure cache lookup.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DEFAULT_CONTEXT_WINDOW = 100_000

_SQL_MAX_INPUT_TOKENS = text(
    """
    SELECT max_input_tokens
    FROM ai_client_model
    WHERE model_id = :model_name OR model_name = :model_name
    ORDER BY (model_id = :model_name) DESC, id ASC
    LIMIT 1
    """
)


class _Connectable(Protocol):
    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]: ...


class LlmModelWindowResolver:
    def __init__(self, db: _Connectable) -> None:
        self._db = db
        self._windows: dict[str, int] = {}

    def max_input_tokens(self, model_name: str | None) -> int:
        """Sync facade used by the domain layer; falls back to 100_000."""
        if not model_name or not model_name.strip():
            return DEFAULT_CONTEXT_WINDOW
        cached = self._windows.get(model_name)
        if cached is None or cached <= 0:
            return DEFAULT_CONTEXT_WINDOW
        return cached

    async def prefill(self, model_names: list[str | None]) -> None:
        """Warm the cache for every model name about to be resolved.

        Unavailable catalog or empty ``max_input_tokens`` is non-fatal: the
        documented default (100_000) then applies, matching the Java behaviour
        when the catalog is unavailable.
        """
        names = [n for n in model_names if n and n.strip()]
        if not names:
            return
        try:
            async with self._db.connect() as connection:
                for name in names:
                    if name in self._windows:
                        continue
                    result = await connection.execute(
                        _SQL_MAX_INPUT_TOKENS, {"model_name": name}
                    )
                    scalar = result.scalar()
                    self._windows[name] = int(scalar) if scalar is not None else 0
        except Exception:  # noqa: BLE001 - catalog unavailability is non-fatal
            return
