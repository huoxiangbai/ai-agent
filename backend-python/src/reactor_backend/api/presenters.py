"""Envelope presentation helpers.

``JSONResponse`` is used instead of a ``response_model`` so nulls survive and key
order matches the Java serialization (Jackson emits fields in declaration order;
``model_dump()`` would drop ``None`` fields if ``exclude_none`` ever leaked in).
Starlette's ``JSONResponse.render`` already sets ``ensure_ascii=False``, so CJK
text is emitted raw — matching Jackson.
"""

from __future__ import annotations

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
