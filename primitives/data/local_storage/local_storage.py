"""Local file storage backend."""

from __future__ import annotations
import os
from abc import ABC, abstractmethod

class StorageBackend(ABC):
    @abstractmethod
    async def read(self, key: str) -> bytes: ...
    @abstractmethod
    async def write(self, key: str, data: bytes) -> None: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...

class LocalStorage(StorageBackend):
    """Local filesystem storage."""

    def __init__(self, base_path: str = "/tmp/storage"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    async def read(self, key: str) -> bytes:
        path = os.path.join(self.base_path, key)
        try:
            import aiofiles
            async with aiofiles.open(path, 'rb') as f:
                return await f.read()
        except ImportError:
            with open(path, 'rb') as f:
                return f.read()

    async def write(self, key: str, data: bytes) -> None:
        path = os.path.join(self.base_path, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            import aiofiles
            async with aiofiles.open(path, 'wb') as f:
                await f.write(data)
        except ImportError:
            with open(path, 'wb') as f:
                f.write(data)

    async def delete(self, key: str) -> None:
        path = os.path.join(self.base_path, key)
        if os.path.exists(path):
            os.remove(path)
