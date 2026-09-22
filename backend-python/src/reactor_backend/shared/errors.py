from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ApiError(Exception):
    info: str
    code: str = "0001"
    status_code: int = 200
