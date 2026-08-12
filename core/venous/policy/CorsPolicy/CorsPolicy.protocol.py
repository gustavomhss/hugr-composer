"""Protocol for CorsPolicy — generated from CorsPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class CorsPolicy(Protocol):
    """Catalog-defined Protocol for CORS evaluation."""

    def evaluate(self, origin: str, method: str, requested_headers: tuple[str, ...]) -> CorsDecision: ...

@runtime_checkable
class OriginMatcher(Protocol):
    """Predicate plugin: does ``origin`` belong to the allowlist?"""

    def matches(self, origin: str) -> bool: ...
