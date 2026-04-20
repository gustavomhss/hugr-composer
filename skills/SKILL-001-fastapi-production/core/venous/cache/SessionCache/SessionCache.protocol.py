"""SessionCache — Protocol-only declaration (copy from SessionCache.py)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class SessionCache(Protocol):
    def get(self, token: str) -> Optional[Mapping[str, Any]]: ...
    def set(self, token: str, value: Mapping[str, Any], ttl_s: int) -> None: ...
    def invalidate(self, token: str) -> None: ...
