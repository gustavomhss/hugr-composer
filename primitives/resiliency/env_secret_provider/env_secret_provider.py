"""Secret provider: EnvSecretProvider."""

from __future__ import annotations
from abc import ABC, abstractmethod

class SecretProvider(ABC):
    @abstractmethod
    async def get_secret(self, key: str) -> str | None: ...
    @abstractmethod
    async def set_secret(self, key: str, value: str) -> None: ...

class EnvSecretProvider(SecretProvider):
    """Environment variable secret provider."""

    def __init__(self):
        self._cache = {}

    async def get_secret(self, key: str) -> str | None:
        import os
        return os.getenv(key)

    async def set_secret(self, key: str, value: str) -> None:
        import os
        os.environ[key] = value
