"""Featured conversations admin routes.

Mirrors ``FeaturedConversationAdminController`` — five routes under
``/api/v1/admin/featured-conversations``. The controller has **no** try/catch and
Java has no ``@ControllerAdvice``, so two error shapes are contract data and must
not be normalised into each other:

* ``IllegalArgumentException`` from create/update → HTTP 500 + Spring
  ``BasicErrorController`` four-key body;
* transport failures (missing ``operator``, missing/malformed body) → four-key at
  the matching 4xx status.

Bodies are coerced field-by-field (:mod:`reactor_backend.api.body_coercion`)
instead of through Pydantic, whose 422 + ``{"detail": ...}`` is forbidden drift.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from reactor_backend.api.body_coercion import (
    BodyError,
    coerce_body_optional_int,
    coerce_body_primitive_int,
    coerce_body_string,
    coerce_body_string_list,
    parse_json_object,
)
from reactor_backend.api.presenters import spring_error_response, success_response
from reactor_backend.application.featured_conversation_admin import (
    FeaturedConversationAdminUseCase,
)
from reactor_backend.domain.featured_admin import (
    ABSENT_PAGE_NO,
    ABSENT_PAGE_SIZE,
    AdminQueryCondition,
    FeaturedAdminRuleError,
    UpsertCommand,
)

router = APIRouter(prefix="/api/v1/admin/featured-conversations", tags=["featured-admin"])


def _use_case(request: Request) -> FeaturedConversationAdminUseCase:
    return cast(
        FeaturedConversationAdminUseCase, request.app.state.featured_admin_use_case
    )


def _upsert_command(payload: dict[str, Any]) -> UpsertCommand:
    return UpsertCommand(
        featured_id=coerce_body_string(payload.get("featuredId"), "featuredId"),
        session_id=coerce_body_string(payload.get("sessionId"), "sessionId"),
        title=coerce_body_string(payload.get("title"), "title"),
        summary=coerce_body_string(payload.get("summary"), "summary"),
        cover_resource_key=coerce_body_string(
            payload.get("coverResourceKey"), "coverResourceKey"
        ),
        cover_url=coerce_body_string(payload.get("coverUrl"), "coverUrl"),
        tags=coerce_body_string_list(payload.get("tags"), "tags"),
        sort_order=coerce_body_optional_int(payload.get("sortOrder"), "sortOrder"),
        operator=coerce_body_string(payload.get("operator"), "operator"),
    )


def _query_condition(payload: dict[str, Any]) -> AdminQueryCondition:
    # Absent vs JSON-null diverge and must not be collapsed. Jackson constructs the
    # VO through its no-arg constructor, which installs the Lombok @Builder.Default
    # (pageNo 1 / pageSize 10), and only then applies setters for the keys actually
    # present — a present JSON null becomes 0. ``payload.get`` cannot tell the two
    # apart, so key presence decides.
    page_no = (
        ABSENT_PAGE_NO
        if "pageNo" not in payload
        else coerce_body_primitive_int(payload["pageNo"], "pageNo")
    )
    page_size = (
        ABSENT_PAGE_SIZE
        if "pageSize" not in payload
        else coerce_body_primitive_int(payload["pageSize"], "pageSize")
    )
    return AdminQueryCondition(
        status=coerce_body_string(payload.get("status"), "status"),
        session_id=coerce_body_string(payload.get("sessionId"), "sessionId"),
        title=coerce_body_string(payload.get("title"), "title"),
        page_no=page_no,
        page_size=page_size,
    )


@router.post("/create")
async def create(request: Request) -> JSONResponse:
    try:
        command = _upsert_command(parse_json_object(await request.body()))
    except BodyError as error:
        return spring_error_response(error.status_code, request.url.path)
    try:
        return success_response(await _use_case(request).create(command))
    except FeaturedAdminRuleError:
        return spring_error_response(500, request.url.path)


@router.put("/update")
async def update(request: Request) -> JSONResponse:
    try:
        command = _upsert_command(parse_json_object(await request.body()))
    except BodyError as error:
        return spring_error_response(error.status_code, request.url.path)
    try:
        return success_response(await _use_case(request).update(command))
    except FeaturedAdminRuleError:
        return spring_error_response(500, request.url.path)


@router.post("/online/{featuredId}")
async def online(
    request: Request, featuredId: str, operator: str | None = None
) -> JSONResponse:
    if operator is None:
        # @RequestParam("operator") is required: MissingServletRequestParameterException
        # -> sendError(400) -> BasicErrorController. An explicit empty value is present.
        return spring_error_response(400, request.url.path)
    return success_response(await _use_case(request).online(featuredId, operator))


@router.post("/offline/{featuredId}")
async def offline(
    request: Request, featuredId: str, operator: str | None = None
) -> JSONResponse:
    if operator is None:
        return spring_error_response(400, request.url.path)
    return success_response(await _use_case(request).offline(featuredId, operator))


@router.post("/query-list")
async def query_list(request: Request) -> JSONResponse:
    try:
        condition = _query_condition(parse_json_object(await request.body()))
    except BodyError as error:
        return spring_error_response(error.status_code, request.url.path)
    return success_response(await _use_case(request).query_list(condition))
