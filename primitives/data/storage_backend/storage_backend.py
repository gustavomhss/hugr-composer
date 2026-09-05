"""Storage backend base."""

from __future__ import annotations
from abc import ABC, abstractmethod

class StorageBackend(ABC):
    @abstractmethod
    async def read(self, key: str) -> bytes: ...
    @abstractmethod
    async def write(self, key: str, data: bytes) -> None: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...
