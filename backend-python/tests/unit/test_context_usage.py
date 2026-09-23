from __future__ import annotations

from dataclasses import dataclass

from reactor_backend.domain.context_usage import (
    DEFAULT_CONTEXT_WINDOW,
    resolve_context_usage,
)


@dataclass
class FakeLlm:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    est_system_tokens: int | None = None
    est_tool_tokens: int | None = None
    est_message_tokens: int | None = None
    est_total_tokens: int | None = None
    model_name: str | None = None


def test_empty_invocations_returns_none() -> None:
    assert resolve_context_usage([]) is None


def test_measured_source_when_prompt_tokens_positive() -> None:
    inv = FakeLlm(prompt_tokens=100, completion_tokens=50)
    usage = resolve_context_usage([inv])
    assert usage is not None
    assert usage["used"] == 100
    assert usage["promptTokens"] == 100
    assert usage["completionTokens"] == 50
    assert usage["source"] == "measured"
    assert usage["sys"] == 0
    assert usage["tools"] == 0
    assert usage["history"] == 0
    assert usage["files"] == 0
    assert usage["estimatedTotal"] == 0


def test_estimate_source_when_prompt_tokens_absent() -> None:
    inv = FakeLlm(
        est_total_tokens=30, est_system_tokens=10, est_tool_tokens=5, est_message_tokens=5
    )
    usage = resolve_context_usage([inv])
    assert usage is not None
    assert usage["source"] == "estimate"
    assert usage["used"] == 30
    assert usage["estimatedTotal"] == 30
    assert usage["promptTokens"] is None
    assert usage["completionTokens"] is None


def test_fallback_sum_when_est_total_zero() -> None:
    inv = FakeLlm(est_system_tokens=10, est_tool_tokens=5, est_message_tokens=5)
    usage = resolve_context_usage([inv])
    assert usage is not None
    assert usage["used"] == 20
    assert usage["estimatedTotal"] == 20


def test_reverse_scan_takes_last_with_used_positive() -> None:
    first = FakeLlm(prompt_tokens=10, completion_tokens=1)
    last = FakeLlm(prompt_tokens=20, completion_tokens=2)
    usage = resolve_context_usage([first, last])
    assert usage is not None
    assert usage["used"] == 20
    assert usage["completionTokens"] == 2


def test_skips_invocations_with_used_zero() -> None:
    zero = FakeLlm()
    good = FakeLlm(prompt_tokens=7)
    usage = resolve_context_usage([zero, good])
    assert usage is not None
    assert usage["used"] == 7


def test_negative_estimates_clamp_to_zero() -> None:
    inv = FakeLlm(est_system_tokens=-5, est_tool_tokens=-1, est_message_tokens=0)
    usage = resolve_context_usage([inv])
    # used = sys+tools+history = 0 → skipped
    assert usage is None


def test_default_window_when_catalog_unavailable() -> None:
    inv = FakeLlm(prompt_tokens=1, model_name="unknown-model")
    usage = resolve_context_usage([inv])
    assert usage is not None
    assert usage["max"] == DEFAULT_CONTEXT_WINDOW


def test_window_from_resolver() -> None:
    inv = FakeLlm(prompt_tokens=1, model_name="m1")

    def resolver(name: str | None) -> int:
        assert name == "m1"
        return 32_000

    usage = resolve_context_usage([inv], resolver)
    assert usage is not None
    assert usage["max"] == 32_000


def test_window_resolver_exception_falls_back() -> None:
    inv = FakeLlm(prompt_tokens=1, model_name="boom")

    def resolver(name: str | None) -> int:
        raise RuntimeError("catalog down")

    usage = resolve_context_usage([inv], resolver)
    assert usage is not None
    assert usage["max"] == DEFAULT_CONTEXT_WINDOW


def test_window_resolver_returning_zero_falls_back() -> None:
    inv = FakeLlm(prompt_tokens=1, model_name="m")
    usage = resolve_context_usage([inv], lambda _n: 0)
    assert usage is not None
    assert usage["max"] == DEFAULT_CONTEXT_WINDOW
