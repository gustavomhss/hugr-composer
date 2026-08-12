"""Protocol for TokenIntrospector — generated from TokenIntrospector.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class TokenIntrospector(Protocol):
    """TokenIntrospector primitive — RFC 7662 + JWT validation with pinned-algorithm policy."""

    def introspect(self, token: str, required_audience: str) -> TokenClaims: ...

@runtime_checkable
class JwksFetcher(Protocol):
    """Adapter that resolves an issuer to its current JWKS."""

    def fetch(self, issuer: str) -> list[SigningKey]: ...

@runtime_checkable
class IntrospectionEndpoint(Protocol):
    """Adapter that calls the authorization server's ``/introspect`` endpoint."""

    def introspect(self, token: str) -> Mapping[str, object]: ...
