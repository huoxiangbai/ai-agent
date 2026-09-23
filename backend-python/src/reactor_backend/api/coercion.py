"""Spring-compatible query-parameter coercion.

``AgentFeaturedConversationController`` declares ``Integer`` params with
``defaultValue``. Spring's ``StringToNumberConverter`` treats missing / empty /
whitespace-only as the default and raises ``MethodArgumentTypeMismatchException``
(HTTP 400 via ``DefaultHandlerExceptionResolver``) for unparsable text.

FastAPI's ``int`` declaration would answer 422 + ``0002`` instead, so the routes
declare ``str | None`` and call into here. The 400 body shape is Spring's
``BasicErrorController`` default (derived, not JVM-probed — registered as
unverified in ``api-contracts.md``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CoercionError(ValueError):
    """Raised when a query parameter cannot be converted to a number."""

    name: str
    raw: str

    def __str__(self) -> str:  # pragma: no cover - message shape is not contract
        return f"Failed to convert value of type 'java.lang.String' for '{self.name}'"


def coerce_int(raw: str | None, default: int) -> int:
    """``StringToNumberConverter`` + controller ``defaultValue`` semantics.

    * missing / ``""`` / whitespace-only → ``default``
    * parsable after ``trim()`` → that integer (Java ``Integer.decode``-ish)
    * otherwise → :class:`CoercionError` (→ HTTP 400)
    """
    if raw is None:
        return default
    trimmed = raw.strip()
    if trimmed == "":
        return default
    try:
        return int(trimmed, 10)
    except ValueError:
        # Java's NumberUtils.parseNumber accepts a leading '+' and hex; Python's
        # int(x, 10) already accepts '+'. Hex/octal are out of scope for these
        # three endpoints' documented contract and are treated as unparsable.
        raise CoercionError(name="int", raw=raw) from None
