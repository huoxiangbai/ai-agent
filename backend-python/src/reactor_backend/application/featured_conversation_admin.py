"""Featured conversations admin use case (the write domain).

Ported from ``FeaturedConversationAdminApplicationService``. The call sequence is
deliberately kept 1:1 with Java — including the extra lookups the repository
adapter performs inside ``upsert`` — because the race windows between them are part
of the observable behaviour under concurrency.

There is no ``@Transactional`` in the Java service: every mapper call is its own
auto-commit statement. ``create`` is therefore **not** atomic (a session that
vanishes between the existence check and the upsert leaves no row and no partial
write), and this module must not wrap the work in one transaction.

Writer fence: :meth:`FeaturedConversationAdminUseCase` calls
``assert_python_owns_writes()`` before any SQL on the four write paths. That is the
application half of the two-layer fence; the other half is the per-writer database
account (``reactor_py_featured_writer``), which can only ever INSERT/UPDATE
``ai_agent_featured_conversation``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol

from reactor_backend.domain.featured_admin import (
    OFFLINE_STATUS,
    ONLINE_STATUS,
    AdminQueryCondition,
    FeaturedAdminRuleError,
    StatusUpdate,
    UpsertCommand,
    UpsertPo,
    build_status_update,
    build_upsert_po,
    generate_featured_id,
    to_admin_payload,
    upsert_guard_blocks,
    validate_create_command,
    validate_update_command,
)
from reactor_backend.domain.featured_conversation import FeaturedConversationRow, is_blank
from reactor_backend.shared.errors import ApiError


class FeaturedConversationAdminStore(Protocol):
    async def query_by_featured_id(
        self, featured_id: str
    ) -> FeaturedConversationRow | None: ...

    async def query_by_session_id(
        self, session_id: str
    ) -> FeaturedConversationRow | None: ...

    async def upsert(self, po: UpsertPo) -> bool: ...

    async def update_status(self, update: StatusUpdate) -> bool: ...

    async def query_admin_list(
        self, condition: AdminQueryCondition
    ) -> Sequence[FeaturedConversationRow]: ...

    async def count_admin_list(self, condition: AdminQueryCondition) -> int: ...


class SessionExistenceChecker(Protocol):
    async def query_session(self, session_id: str) -> object | None: ...


class WriteOwnerFence(Protocol):
    def assert_python_owns_writes(self) -> None: ...


class SettingsWriteOwnerFence:
    """Fail-closed owner flag (``REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER``).

    Default is ``"java"``: until the operator flips it to ``"python"`` as part of
    the documented cutover order, every write path refuses **before** any SQL and
    answers the ``0001`` envelope rather than a fake success.
    """

    def __init__(self, owner: str) -> None:
        self._owner = owner

    def assert_python_owns_writes(self) -> None:
        if self._owner != "python":
            raise ApiError(
                info=f"featured-admin 写域 owner={self._owner}，Python 拒绝写入",
                code="0001",
                status_code=200,
            )


class _Clock(Protocol):
    def __call__(self) -> datetime: ...


def _system_clock() -> datetime:
    return datetime.now()


class FeaturedConversationAdminUseCase:
    def __init__(
        self,
        store: FeaturedConversationAdminStore,
        session_checker: SessionExistenceChecker,
        fence: WriteOwnerFence,
        clock: _Clock | None = None,
    ) -> None:
        self._store = store
        self._session_checker = session_checker
        self._fence = fence
        self._clock: _Clock = clock if clock is not None else _system_clock

    async def create(self, command: UpsertCommand | None) -> bool:
        self._fence.assert_python_owns_writes()
        session_id = validate_create_command(command)
        if await self._session_checker.query_session(session_id) is None:
            raise FeaturedAdminRuleError("sessionId 对应会话不存在")
        assert command is not None
        effective = replace(
            command,
            featured_id=generate_featured_id(session_id),
            session_id=session_id,
        )
        # Java's guard sits at the top of repo.upsert, after the service's own
        # pre-checks and before its resolve queries. It can never fire here — the
        # keys were just validated/derived — but it stays so both paths read 1:1.
        if upsert_guard_blocks(effective):
            return False
        po = build_upsert_po(effective, await self._resolve_existing(effective), now=self._clock())
        return await self._store.upsert(po)

    async def update(self, command: UpsertCommand | None) -> bool:
        self._fence.assert_python_owns_writes()
        featured_id = validate_update_command(command)
        # Java checks existence first (IllegalArgumentException) and then lets
        # upsert re-resolve ``existing`` — two identical SELECTs back to back.
        if await self._store.query_by_featured_id(featured_id) is None:
            raise FeaturedAdminRuleError("featuredId 不存在")
        assert command is not None
        # Java's upsert refuses a blank featuredId/sessionId without writing. For
        # update that means "no sessionId in the body" → data:false, row unchanged,
        # and no resolve SELECTs either.
        if upsert_guard_blocks(command):
            return False
        po = build_upsert_po(command, await self._resolve_existing(command), now=self._clock())
        return await self._store.upsert(po)

    async def online(self, featured_id: str, operator: str | None) -> bool:
        self._fence.assert_python_owns_writes()
        return await self._update_status(featured_id, ONLINE_STATUS, operator)

    async def offline(self, featured_id: str, operator: str | None) -> bool:
        self._fence.assert_python_owns_writes()
        return await self._update_status(featured_id, OFFLINE_STATUS, operator)

    async def query_list(self, condition: AdminQueryCondition) -> dict[str, Any]:
        """Admin list is a read — it is not behind the writer fence.

        It is routed to Python by the same Nginx cutover as the writes, but it
        cannot produce a data write and stays servable under ``reactor_py_ro``.
        """
        total = await self._store.count_admin_list(condition)
        rows = await self._store.query_admin_list(condition)
        return {"total": total, "list": [to_admin_payload(row) for row in rows]}

    async def _update_status(
        self, featured_id: str, status: str, operator: str | None
    ) -> bool:
        # Repository-level guards: blank id / blank status / missing row are all
        # ``false`` at HTTP 200 + data:false, never an exception.
        if is_blank(featured_id) or is_blank(status):
            return False
        existing = await self._store.query_by_featured_id(featured_id)
        if existing is None:
            return False
        update = build_status_update(
            featured_id, status, operator, existing, now=self._clock()
        )
        return await self._store.update_status(update)

    async def _resolve_existing(
        self, command: UpsertCommand
    ) -> FeaturedConversationRow | None:
        existing = await self._store.query_by_featured_id(command.featured_id or "")
        if existing is not None:
            return existing
        return await self._store.query_by_session_id(command.session_id or "")
