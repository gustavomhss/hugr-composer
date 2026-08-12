"""Protocol for CurrentPrincipal — generated from CurrentPrincipal.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class PrincipalProvider(Protocol):
    """Contract for the single registered provider that binds a principal."""

    def resolve(self, credential: str | None) -> CurrentPrincipal: ...
