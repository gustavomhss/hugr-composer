from __future__ import annotations
from abc import ABC
from abc import abstractmethod


class StorageBackend(ABC):
    """Abstract storage backend.  Both implementations share this interface."""

    @abstractmethod
    async def save(self, file_obj: object, content_type: str) -> tuple[str, int]:
        """Persist *file_obj* and return ``(stored_key, size_bytes)``.

        Args:
            file_obj: File-like object with a ``read`` method.
            content_type: MIME type of the file.

        Returns:
            Tuple of ``(stored_key, size_bytes)``.
        """

    @abstractmethod
    async def get_url(self, stored_key: str, expires_in: int=3600) -> str:
        """Return a URL (presigned for S3, file path for local) for *stored_key*.

        Args:
            stored_key: UUID-based storage key.
            expires_in: URL TTL in seconds (S3 only).

        Returns:
            Accessible URL string.
        """

    @abstractmethod
    async def delete(self, stored_key: str) -> None:
        """Remove the object identified by *stored_key* from storage.

        Args:
            stored_key: UUID-based storage key.
        """
