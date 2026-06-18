"""Custom exception (reused from the platform ``custom_exception.py``)."""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class CustomException(Exception, Generic[T]):
    def __init__(self, status_code: int, detail: str, data: Optional[T] = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.data = data
        super().__init__(detail)
