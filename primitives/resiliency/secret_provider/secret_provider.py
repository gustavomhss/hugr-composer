"""Secret provider base."""

from __future__ import annotations
from abc import ABC, abstractmethod

class SecretProvider(ABC):
    @abstractmethod
    async def get_secret(self, key: str) -> str | None: ...
    @abstractmethod
    async def set_secret(self, key: str, value: str) -> None: ...
