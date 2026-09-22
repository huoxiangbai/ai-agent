from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class NormalizationRules:
    """Case-local allowlist of values that are known to be nondeterministic."""

    ignored_json_pointers: tuple[str, ...] = ()
    ignored_cookie_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HttpCase:
    name: str
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: JsonValue = None
    compared_headers: tuple[str, ...] = ()
    normalization: NormalizationRules = field(default_factory=NormalizationRules)


@dataclass(frozen=True, slots=True)
class CookieSnapshot:
    name: str
    value_fingerprint: str
    attributes: dict[str, str | bool]


@dataclass(frozen=True, slots=True)
class HttpSnapshot:
    status_code: int
    content_type: str | None
    headers: dict[str, str]
    cookies: tuple[CookieSnapshot, ...]
    body: JsonValue

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Difference:
    path: str
    java: object
    python: object
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SseEvent:
    kind: str
    event: str | None = None
    data: JsonValue = None
    event_id: str | None = None
    retry: int | None = None
    comment: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SseCapture:
    status_code: int | None
    content_type: str | None
    events: tuple[SseEvent, ...]
    termination: str
    error_type: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)
