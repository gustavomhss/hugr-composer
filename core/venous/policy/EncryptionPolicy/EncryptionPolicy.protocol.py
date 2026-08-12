"""Protocol for EncryptionPolicy — generated from EncryptionPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class EncryptionRegistry(Protocol):
    """Catalog-defined Protocol."""

    def bind(self, policy: EncryptionPolicy) -> None: ...
    def resolve(self, data_class: str) -> EncryptionPolicy: ...
    def require_tls(self, endpoint: str) -> None: ...
