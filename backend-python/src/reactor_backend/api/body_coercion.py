"""Jackson-compatible request-body coercion.

``FeaturedConversationAdminController`` binds ``@RequestBody`` POJOs. FastAPI's
Pydantic models would answer 422 + ``{"detail": ...}`` on a type mismatch — an
explicitly forbidden drift. Jackson raises ``HttpMessageNotReadableException``,
which this controller does not catch and which lands in ``response.sendError(...)``
→ Spring's ``BasicErrorController`` four-key body. The routes therefore read the
raw body and coerce fields here.

Field-level rules mirror Spring's default ``ObjectMapper`` coercion:

* a JSON string bound to ``String`` is taken as-is (no trim — ``update`` relies on
  passing ``featuredId``/``sessionId`` through untrimmed);
* a JSON number/boolean bound to ``String`` is coerced via ``String.valueOf``;
* a JSON scalar bound to ``Integer`` is coerced when it looks like an int
  (``ACCEPT_FLOAT_AS_INT`` is on: ``1.0`` → 1, ``1.5`` → 400);
* a **JSON-null** primitive ``int`` is Java ``0`` (``FAIL_ON_NULL_FOR_PRIMITIVES``
  is off), so the setter overwrites the field initializer with ``0``;
* a **missing** primitive ``int`` never reaches the setter — Jackson's no-arg
  construction leaves the Lombok ``@Builder.Default`` in place (``pageNo`` 1,
  ``pageSize`` 10). This function is only ever called for keys that are present;
  the caller decides what an absent key means;
* a JSON array/object bound to a scalar (or the reverse) is 400.

The ``null``-body case is deliberately 500, not 400: a present ``null`` token is a
present body, Jackson returns Java ``null``, and ``toCommand(null)`` NPEs inside a
controller with no try/catch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_JAVA_INT_MIN = -2147483648
_JAVA_INT_MAX = 2147483647


@dataclass
class BodyError(ValueError):
    """Maps to Spring's ``BasicErrorController`` at ``status_code``."""

    status_code: int = 400
    field: str | None = None


def parse_json_object(raw: bytes) -> dict[str, Any]:
    """Parse the request body into a JSON object the way Jackson would.

    * missing / empty body → 400 (``Required request body is missing``);
    * malformed JSON / non-object top level → 400 (``HttpMessageNotReadableException``);
    * JSON ``null`` → 500 (Jackson yields Java null, then the controller NPEs).
    """
    if raw is None or raw.strip() == b"":
        raise BodyError(400)
    try:
        payload: Any = json.loads(raw)
    except ValueError:
        raise BodyError(400) from None
    if payload is None:
        raise BodyError(500)
    if not isinstance(payload, dict):
        raise BodyError(400)
    return payload


def coerce_body_string(value: Any, field: str) -> str | None:
    """``String`` field: JSON null → ``None``, scalars via ``String.valueOf``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    raise BodyError(400, field)


def coerce_body_optional_int(value: Any, field: str) -> int | None:
    """Boxed ``Integer`` field: JSON null stays Java ``null``."""
    if value is None:
        return None
    return _coerce_int_like(value, field)


def coerce_body_primitive_int(value: Any, field: str) -> int:
    """Primitive ``int`` field: JSON null → ``0``.

    Only called for keys that are *present* in the body; an absent key keeps the
    Lombok ``@Builder.Default`` and is decided by the caller before we get here.
    """
    if value is None:
        return 0
    return _coerce_int_like(value, field)


def coerce_body_string_list(value: Any, field: str) -> list[str | None] | None:
    """``List<String>`` field: JSON null → ``None``, elements coerced like ``String``."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise BodyError(400, field)
    return [
        coerce_body_string(item, f"{field}[{index}]") for index, item in enumerate(value)
    ]


def _coerce_int_like(value: Any, field: str) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return _check_java_int(value, field)
    if isinstance(value, float):
        # ACCEPT_FLOAT_AS_INT is on by default, but only for whole values.
        if not value.is_integer():
            raise BodyError(400, field)
        return _check_java_int(int(value), field)
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed == "":
            raise BodyError(400, field)
        try:
            return _check_java_int(int(trimmed, 10), field)
        except ValueError:
            raise BodyError(400, field) from None
    raise BodyError(400, field)


def _check_java_int(value: int, field: str) -> int:
    if value < _JAVA_INT_MIN or value > _JAVA_INT_MAX:
        raise BodyError(400, field)
    return value
