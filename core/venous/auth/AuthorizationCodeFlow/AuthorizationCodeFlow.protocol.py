"""Protocol for AuthorizationCodeFlow — generated from AuthorizationCodeFlow.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuthorizationCodeFlow(Protocol):
    """AuthorizationCodeFlow primitive — OAuth 2.1 / PKCE S256 authorization-code grant."""

    def begin(self, scopes: list[str]) -> AuthorizationRequest: ...
    def exchange(self, code: str, state: str, stored: AuthorizationRequest) -> dict[str, object]: ...
