"""Protocol for ConfigBinding — generated from ConfigBinding.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class ConfigProvider(Protocol):
    """A pluggable source of raw string values keyed by dotted/underscore path."""

    def name(self) -> str: ...
    def pinned(self) -> bool: ...
    def values(self, prefix: str) -> Mapping[str, str]: ...

@runtime_checkable
class SecretsProviderLike(Protocol):
    """Minimal SecretsVault interface sufficient for ConfigBinding."""

    def get(self, key: str) -> str: ...

@runtime_checkable
class ConfigBinding(Protocol):
    """ConfigBinding primitive — namespaced, typed, strict config binder."""

    def bind(self, prefix: str, schema: type[T]) -> T: ...
    def reload(self) -> None: ...
