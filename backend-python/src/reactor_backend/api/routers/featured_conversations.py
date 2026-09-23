"""Public featured-conversation reads.

Mirrors ``AgentFeaturedConversationController``. Query parameters are declared
as ``str | None`` so FastAPI cannot 422 on unparsable input — Spring would 400.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from reactor_backend.api.coercion import CoercionError, coerce_int
from reactor_backend.api.presenters import spring_error_response, success_response
from reactor_backend.application.featured_conversation_query import (
    FeaturedConversationQueryUseCase,
)
from reactor_backend.domain.featured_conversation import (
    HOME_DEFAULT_LIMIT,
    LIST_DEFAULT_PAGE_NO,
    LIST_DEFAULT_PAGE_SIZE,
)

router = APIRouter(prefix="/api/agent/featured-conversations", tags=["featured"])


def _use_case(request: Request) -> FeaturedConversationQueryUseCase:
    return cast(
        FeaturedConversationQueryUseCase, request.app.state.featured_query_use_case
    )


@router.get("/home")
async def home(request: Request, limit: str | None = None) -> JSONResponse:
    try:
        resolved_limit = coerce_int(limit, HOME_DEFAULT_LIMIT)
    except CoercionError:
        # Spring: MethodArgumentTypeMismatchException -> sendError(400) ->
        # BasicErrorController. Not a 0002 envelope, not a 422 (measured).
        return spring_error_response(400, request.url.path)
    cards = await _use_case(request).query_home_cards(resolved_limit)
    return success_response(cards)


@router.get("")
async def featured_list(
    request: Request,
    pageNo: str | None = None,
    pageSize: str | None = None,
) -> JSONResponse:
    try:
        resolved_page_no = coerce_int(pageNo, LIST_DEFAULT_PAGE_NO)
        resolved_page_size = coerce_int(pageSize, LIST_DEFAULT_PAGE_SIZE)
    except CoercionError:
        return spring_error_response(400, request.url.path)
    page = await _use_case(request).query_public_list(resolved_page_no, resolved_page_size)
    return success_response(page)


@router.get("/{featuredId}")
async def featured_detail(request: Request, featuredId: str) -> JSONResponse:
    detail: dict[str, Any] | None = await _use_case(request).query_detail(featuredId)
    return success_response(detail)
