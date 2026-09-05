"""Secret provider: VaultSecretProvider."""

from __future__ import annotations
from abc import ABC, abstractmethod

class SecretProvider(ABC):
    @abstractmethod
    async def get_secret(self, key: str) -> str | None: ...
    @abstractmethod
    async def set_secret(self, key: str, value: str) -> None: ...

class VaultSecretProvider(SecretProvider):
    """HashiCorp Vault secret provider."""

    def __init__(self):
        self._cache = {}

    async def get_secret(self, key: str) -> str | None:
        return self._cache.get(key)

    async def set_secret(self, key: str, value: str) -> None:
        self._cache[key] = value
