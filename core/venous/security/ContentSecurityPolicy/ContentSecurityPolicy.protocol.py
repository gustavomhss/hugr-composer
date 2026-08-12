"""Protocol for ContentSecurityPolicy — generated from ContentSecurityPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable, Iterator, Mapping

@runtime_checkable
class ContentSecurityPolicy(Protocol):
    """ContentSecurityPolicy primitive — compose, serialize, enforce a CSP header."""

    def with_directive(self, directive: Directive) -> ContentSecurityPolicy: ...
    def with_nonce(self, nonce: str) -> ContentSecurityPolicy: ...
    def render_header(self) -> tuple[str, str]: ...
