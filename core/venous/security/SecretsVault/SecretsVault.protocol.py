"""Protocol for SecretsVault — generated from SecretsVault.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterator, Mapping

@runtime_checkable
class SecretsVault(Protocol):
    """SecretsVault primitive — fetch, cache, rotate, audit named secrets."""

    def get(self, name: str) -> SecretVersion: ...
    def rotate(self, name: str) -> SecretVersion: ...
    def invalidate(self, name: str) -> None: ...

@runtime_checkable
class SecretBackend(Protocol):
    """Adapter shape every storage backend MUST implement."""

    def fetch(self, name: str) -> tuple[int, bytes, int | None]: ...
    def rotate(self, name: str) -> tuple[int, bytes, int | None]: ...

@runtime_checkable
class Clock(Protocol):
    """SecretsVault primitive — fetch, cache, rotate, audit named secrets."""

    def now_s(self) -> float: ...
