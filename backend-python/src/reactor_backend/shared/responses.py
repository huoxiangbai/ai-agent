from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: str
    info: str
    data: T | None = None

    @classmethod
    def success(cls, data: T | None = None) -> ApiResponse[T]:
        return cls(code="0000", info="成功", data=data)

    @classmethod
    def failure(cls, info: str, code: str = "0001") -> ApiResponse[T]:
        return cls(code=code, info=info, data=None)
