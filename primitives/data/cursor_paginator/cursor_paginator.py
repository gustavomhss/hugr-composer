"""Cursor-based pagination."""

from __future__ import annotations
from typing import Generic, TypeVar, Optional

T = TypeVar('T')

class CursorPaginator(Generic[T]):
    """Generic cursor paginator."""

    def __init__(self, page_size: int = 50):
        self.page_size = page_size

    def paginate(self, items: list[T], cursor: Optional[str] = None) -> tuple[list[T], Optional[str]]:
        return items[:self.page_size], None
