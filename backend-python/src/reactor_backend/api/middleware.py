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


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        candidate = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else str(uuid.uuid4())
        token = bind_request_id(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.monotonic()
        logger = structlog.get_logger(__name__)
        try:
            response = await call_next(request)
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
