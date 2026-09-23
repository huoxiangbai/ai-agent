from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class NormalizationRules:
    """Case-local allowlist of values that are known to be nondeterministic.

    The same pointer list drives two complementary behaviours:

    * value tolerance — :func:`reactor_backend.contracts.normalize.normalize_json`
      replaces allowlisted leaves with a sentinel at capture time;
    * additive tolerance —
      :func:`reactor_backend.contracts.normalize.drop_additive` deletes
      candidate-only leaves at compare time.

    Pointers address the compared payload: the capture document
    (``HttpSnapshot.as_dict()``, so ``/body/data/visitorId`` or
    ``/cookies/*/attributes/expires``) for HTTP, and the event's ``data`` value
    for SSE. ``ignored_cookie_values`` is separate and names cookies whose raw
    value never enters a golden.

    There is deliberately no global ignore list.
    """

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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CookieSnapshot:
        return cls(
            name=_as_str(value, "name"),
            value_fingerprint=_as_str(value, "value_fingerprint"),
            attributes=_as_attributes(value, "attributes"),
        )


@dataclass(frozen=True, slots=True)
class HttpSnapshot:
    status_code: int
    content_type: str | None
    headers: dict[str, str]
    cookies: tuple[CookieSnapshot, ...]
    body: JsonValue

    def as_dict(self) -> dict[str, object]:
        # Explicit rather than dataclasses.asdict: that helper keeps tuple
        # containers, and a tuple is not a JsonValue — the allowlist walker and
        # json.dumps both need a plain list here.
        return {
            "status_code": self.status_code,
            "content_type": self.content_type,
            "headers": dict(self.headers),
            "cookies": [cookie.as_dict() for cookie in self.cookies],
            "body": self.body,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HttpSnapshot:
        cookies: list[CookieSnapshot] = []
        for entry in _as_array(value, "cookies"):
            cookies.append(CookieSnapshot.from_dict(_as_object(entry, "cookies entry")))
        return cls(
            status_code=_as_int(value, "status_code"),
            content_type=_as_optional_str(value, "content_type"),
            headers=_as_str_map(value, "headers"),
            cookies=tuple(cookies),
            body=_as_json(value["body"]) if "body" in value else None,
        )


@dataclass(frozen=True, slots=True)
class CaptureCase:
    """One case entry of a recorded capture document."""

    name: str
    snapshot: HttpSnapshot | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        if self.error is not None:
            return {"name": self.name, "error": self.error}
        if self.snapshot is None:
            raise ValueError(f"{self.name}: capture case needs a snapshot or an error")
        return {"name": self.name, "snapshot": self.snapshot.as_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CaptureCase:
        name = _as_str(value, "name")
        error = _as_optional_str(value, "error")
        if error is not None:
            return cls(name=name, error=error)
        if "snapshot" not in value:
            raise ValueError(f"{name}: capture case needs a snapshot or an error")
        return cls(name=name, snapshot=HttpSnapshot.from_dict(_as_object(value["snapshot"], name)))


@dataclass(frozen=True, slots=True)
class CaptureFile:
    """Recorded capture document shared by goldens and candidate responses.

    ``mode`` is ``java-baseline`` for a Java golden and ``python-capture`` for a
    candidate response file. ``base_url`` is recorded for audit only and is not
    part of any comparison.
    """

    mode: str
    base_url: str | None
    cases: tuple[CaptureCase, ...]
    skipped: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "base_url": self.base_url,
            "cases": [case.as_dict() for case in self.cases],
            "skipped": list(self.skipped),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CaptureFile:
        cases: list[CaptureCase] = []
        for entry in _as_array(value, "cases"):
            cases.append(CaptureCase.from_dict(_as_object(entry, "cases entry")))
        skipped: list[str] = []
        for entry in _as_array(value, "skipped"):
            if not isinstance(entry, str):
                raise ValueError("skipped entries must be strings")
            skipped.append(entry)
        return cls(
            mode=_as_str(value, "mode"),
            base_url=_as_optional_str(value, "base_url"),
            cases=tuple(cases),
            skipped=tuple(skipped),
        )

    def snapshots(self) -> dict[str, HttpSnapshot]:
        collected: dict[str, HttpSnapshot] = {}
        for case in self.cases:
            if case.snapshot is not None:
                collected[case.name] = case.snapshot
        return collected

    def errors(self) -> dict[str, str]:
        collected: dict[str, str] = {}
        for case in self.cases:
            if case.error is not None:
                collected[case.name] = case.error
        return collected


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

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SseEvent:
        retry_raw = value.get("retry")
        if retry_raw is None:
            retry: int | None = None
        elif isinstance(retry_raw, bool) or not isinstance(retry_raw, int):
            raise ValueError("retry must be an integer or null")
        else:
            retry = retry_raw
        return cls(
            kind=_as_str(value, "kind"),
            event=_as_optional_str(value, "event"),
            data=_as_json(value["data"]) if "data" in value else None,
            event_id=_as_optional_str(value, "event_id"),
            retry=retry,
            comment=_as_optional_str(value, "comment"),
        )


@dataclass(frozen=True, slots=True)
class SseCapture:
    status_code: int | None
    content_type: str | None
    events: tuple[SseEvent, ...]
    termination: str
    error_type: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "content_type": self.content_type,
            "events": [event.as_dict() for event in self.events],
            "termination": self.termination,
            "error_type": self.error_type,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SseCapture:
        status_raw = value.get("status_code")
        if status_raw is None:
            status_code: int | None = None
        elif isinstance(status_raw, bool) or not isinstance(status_raw, int):
            raise ValueError("status_code must be an integer or null")
        else:
            status_code = status_raw
        events: list[SseEvent] = []
        for entry in _as_array(value, "events"):
            events.append(SseEvent.from_dict(_as_object(entry, "events entry")))
        return cls(
            status_code=status_code,
            content_type=_as_optional_str(value, "content_type"),
            events=tuple(events),
            termination=_as_str(value, "termination"),
            error_type=_as_optional_str(value, "error_type"),
        )


def _as_object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _as_array(value: Mapping[str, object], key: str) -> list[object]:
    if key not in value:
        raise ValueError(f"missing field: {key}")
    item = value[key]
    if isinstance(item, (str, bytes)) or not isinstance(item, list | tuple):
        raise ValueError(f"{key} must be an array")
    return list(item)


def _as_str(value: Mapping[str, object], key: str) -> str:
    if key not in value:
        raise ValueError(f"missing field: {key}")
    item = value[key]
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string")
    return item


def _as_optional_str(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string or null")
    return item


def _as_int(value: Mapping[str, object], key: str) -> int:
    if key not in value:
        raise ValueError(f"missing field: {key}")
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} must be an integer")
    return item


def _as_str_map(value: Mapping[str, object], key: str) -> dict[str, str]:
    if key not in value:
        raise ValueError(f"missing field: {key}")
    item = _as_object(value[key], key)
    result: dict[str, str] = {}
    for name, entry in item.items():
        if not isinstance(name, str) or not isinstance(entry, str):
            raise ValueError(f"{key} must contain string keys and values")
        result[name] = entry
    return result


def _as_attributes(value: Mapping[str, object], key: str) -> dict[str, str | bool]:
    if key not in value:
        raise ValueError(f"missing field: {key}")
    item = _as_object(value[key], key)
    result: dict[str, str | bool] = {}
    for name, entry in item.items():
        if isinstance(entry, bool):
            result[str(name)] = entry
        elif isinstance(entry, str):
            result[str(name)] = entry
        else:
            raise ValueError(f"{key}.{name} must be a string or boolean")
    return result


def _as_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_as_json(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _as_json(item) for key, item in value.items()}
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")
