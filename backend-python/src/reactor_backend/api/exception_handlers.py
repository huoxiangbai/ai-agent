from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from reactor_backend.api.middleware import JAVA_COMPAT_VARY
from reactor_backend.api.presenters import error_response, spring_error_response
from reactor_backend.shared.errors import ApiError
from reactor_backend.shared.responses import ApiResponse


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        payload = ApiResponse[object].failure(error.info, error.code)
        return JSONResponse(status_code=error.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        structlog.get_logger(__name__).info(
            "request_validation_failed",
            error_count=len(error.errors()),
        )
        payload = ApiResponse[object].failure("非法参数", "0002")
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        """Transport-level 4xx must look like Java's, not FastAPI's.

        FastAPI's default is ``{"detail": "Method Not Allowed"}``. Java's
        ``DefaultHandlerExceptionResolver`` turns the same situation into
        ``sendError`` + ``BasicErrorController``, i.e. the four-key error body.
        Measured 2026-09-23: the ``Allow`` header (``GET``) matches on both
        sides and is carried across unchanged.
        """
        response = spring_error_response(error.status_code, request.url.path)
        for name, value in (error.headers or {}).items():
            response.headers[name] = value
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        structlog.get_logger(__name__).exception(
            "unhandled_request_error",
            error_type=type(error).__name__,
        )
        response = spring_error_response(500, request.url.path)
        # Starlette routes ``Exception`` to ``ServerErrorMiddleware``, which sits
        # *outside* the user middleware stack — so the Vary stamping in
        # RequestContextMiddleware never sees this response. Java's CorsFilter does
        # run (it is a servlet filter, below the error dispatch), which is why the
        # unhandled-500 body is the one response that would otherwise differ.
        # Appending here cannot double up: nothing below adds it for this path.
        for value in JAVA_COMPAT_VARY:
            response.headers.append("Vary", value)
        return response


# ``error_response`` stays exported for application-level failures that want an
# explicit status plus the ``{code, info, data}`` envelope rather than Spring's
# transport-error body. Importing it here keeps the two shapes discoverable
# together.
__all__ = ["install_exception_handlers", "error_response"]
