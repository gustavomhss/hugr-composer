"""Protocol for CsrfGuard — generated from CsrfGuard.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class CsrfGuard(Protocol):
    """CsrfGuard primitive — per-session CSRF token issuer and verifier."""

    def issue(self, session_id: str) -> str: ...
    def verify(self, session_id: str, submitted_token: str) -> None: ...
