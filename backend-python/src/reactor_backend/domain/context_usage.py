"""Context usage snapshot for a run.

Ported from ``ConversationHistoryReplayService.resolveContextUsage``. The model
window (``max``) is resolved through a port so the domain layer stays free of the
model catalog.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

DEFAULT_CONTEXT_WINDOW = 100_000


def _non_negative(value: int | None) -> int:
    return 0 if value is None else max(0, value)


def resolve_context_usage(
    invocations: Sequence[Any],
    max_input_tokens: Callable[[str | None], int] | None = None,
) -> dict[str, Any] | None:
    """Reverse-scan LLM invocations and return the last one with ``used > 0``."""
    if not invocations:
        return None
    for invocation in reversed(invocations):
        if invocation is None:
            continue
        sys_tokens = _non_negative(getattr(invocation, "est_system_tokens", None))
        tools = _non_negative(getattr(invocation, "est_tool_tokens", None))
        history = _non_negative(getattr(invocation, "est_message_tokens", None))
        estimated = _non_negative(getattr(invocation, "est_total_tokens", None))
        prompt_tokens = getattr(invocation, "prompt_tokens", None)
        completion_tokens = getattr(invocation, "completion_tokens", None)
        if prompt_tokens is not None and prompt_tokens > 0:
            used = prompt_tokens
        elif estimated > 0:
            used = estimated
        else:
            used = sys_tokens + tools + history
        if used <= 0:
            continue
        window = _resolve_context_window(
            getattr(invocation, "model_name", None), max_input_tokens
        )
        return {
            "sys": sys_tokens,
            "tools": tools,
            "history": history,
            "files": 0,
            "max": window,
            "used": used,
            "estimatedTotal": estimated if estimated > 0 else sys_tokens + tools + history,
            "promptTokens": (
                prompt_tokens if prompt_tokens is not None and prompt_tokens > 0 else None
            ),
            "completionTokens": (
                completion_tokens
                if completion_tokens is not None and completion_tokens > 0
                else None
            ),
            "source": "measured" if prompt_tokens is not None and prompt_tokens > 0 else "estimate",
        }
    return None


def _resolve_context_window(
    model_name: str | None,
    max_input_tokens: Callable[[str | None], int] | None,
) -> int:
    if model_name and model_name.strip() and max_input_tokens is not None:
        try:
            resolved = max_input_tokens(model_name)
            if resolved > 0:
                return resolved
        except Exception:  # noqa: BLE001 - history replay must not fail on catalog hiccups
            return DEFAULT_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW
