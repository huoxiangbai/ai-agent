"""Envelope presentation helpers.

``JSONResponse`` is used instead of a ``response_model`` so nulls survive and key
order matches the Java serialization (Jackson emits fields in declaration order;
``model_dump()`` would drop ``None`` fields if ``exclude_none`` ever leaked in).
Starlette's ``JSONResponse.render`` already sets ``ensure_ascii=False``, so CJK
text is emitted raw — matching Jackson.

Two shapes live here, and which one a handler uses is contract data:

* :func:`success_response` — the ``{code, info, data}`` envelope Java returns from
  every business handler (including "not found", which is HTTP 200 + ``data:null``).
* :func:`spring_error_response` — Spring Boot's auto-configured
  ``BasicErrorController`` body, which is what Java emits for *transport* errors.
  Java has no ``@ControllerAdvice``: a type mismatch on a query parameter, an
  unsupported method, an unmapped path or an unhandled exception all end in
  ``response.sendError(...)`` and come back shaped like this. Mixing the two (or
  inventing a third, like FastAPI's ``{"detail": ...}``) is exactly the drift the
  cutover must not introduce.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from fastapi.responses import JSONResponse

SUCCESS_CODE = "0000"
SUCCESS_INFO = "成功"


def success_response(data: Any) -> JSONResponse:
    return JSONResponse(content={"code": SUCCESS_CODE, "info": SUCCESS_INFO, "data": data})


def error_response(status_code: int, info: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "info": info, "data": None},
    )


def spring_error_response(status_code: int, path: str) -> JSONResponse:
    """Reproduce Spring Boot's ``BasicErrorController`` JSON body.

    Measured 2026-09-23 against ``--spring.profiles.active=prod`` (throwaway
    MySQL, no ``server.error.*`` overrides) — exactly four keys, in this order::

        {"timestamp":"2026-09-23T10:08:05.470+00:00","status":400,
         "error":"Bad Request","path":"/api/agent/featured-conversations/home"}

    ``timestamp`` is UTC, millisecond precision, ``+00:00`` offset (not ``Z``) —
    it is Jackson's ``java.util.Date`` rendering, not ``Instant``. ``path`` is the
    request URI without the query string. No ``message``, no ``requestId``.
    """
    now = datetime.now(UTC)
    timestamp = f"{now.strftime('%Y-%m-%dT%H:%M:%S')}.{now.microsecond // 1000:03d}+00:00"
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:  # pragma: no cover - Java only ever sends registered codes
        phrase = "Error"
    return JSONResponse(
        status_code=status_code,
        content={
            "timestamp": timestamp,
            "status": status_code,
            "error": phrase,
            "path": path,
        },
    )
