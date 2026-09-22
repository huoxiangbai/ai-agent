from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        structlog.get_logger(__name__).exception(
            "unhandled_request_error",
            error_type=type(error).__name__,
        )
        payload = ApiResponse[object].failure("未知失败")
        return JSONResponse(status_code=500, content=payload.model_dump())
