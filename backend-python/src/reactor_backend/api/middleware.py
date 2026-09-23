from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from reactor_backend.shared.request_context import bind_request_id, reset_request_id

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# Java's global ``CorsFilter`` (Spring's ``CorsFilter`` registration) stamps these
# on every response, including non-CORS ones like ``/web/health``. Measured
# 2026-09-23. Reproduced here so a response is wire-identical whether nginx sent
# it to reactor_backend or reactor_backend_python — a shared cache in front of
# the public featured GETs would otherwise key differently across the cutover.
# Pure compatibility shim: remove together with the Java backend.
JAVA_COMPAT_VARY: tuple[str, ...] = (
    "Origin",
    "Access-Control-Request-Method",
    "Access-Control-Request-Headers",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id to the log context, echoing it only when asked.

    Java never sends ``X-Request-ID``. Emitting it unconditionally made the
    public HTTP surface differ from the reference backend the moment these
    routes cut over, so the header is now written **only** when the client sent
    one (echo, or a sanitised replacement if the inbound value was unsafe).
    A client that does not ask for correlation — the SPA, a cache, the cutover
    drill — sees a byte-identical wire either way. Log lines always carry
    ``request_id``, which is where the value is actually consumed.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        candidate = request.headers.get(REQUEST_ID_HEADER, "")
        requested = candidate != ""
        request_id = candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else str(uuid.uuid4())
        token = bind_request_id(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.monotonic()
        logger = structlog.get_logger(__name__)
        try:
            response = await call_next(request)
            for value in JAVA_COMPAT_VARY:
                response.headers.append("Vary", value)
            if requested:
                response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()
            reset_request_id(token)
