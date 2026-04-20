from __future__ import annotations
from pathlib import Path
import os


class LocalStorageBackend:
    """Filesystem fallback storage for development and testing."""

    def __init__(self) -> None:
        """Initialise local storage under ``EXPORT_LOCAL_DIR`` (default: /tmp/exports)."""
        self._root = Path(os.getenv('EXPORT_LOCAL_DIR', '/tmp/exports'))
        self._root.mkdir(parents=True, exist_ok=True)

    async def save(self, buf: BinaryIO, key: str, *, content_type: str) -> None:
        """Write buffer to local filesystem.

        Args:
            buf: File-like object to write.
            key: Relative path within the local export directory.
            content_type: Ignored for local storage.
        """
        dest = self._root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(buf.read() if isinstance(buf, io.IOBase) else bytes(buf.read()))

    async def presigned_url(self, key: str, *, expires_in: int=86400) -> str:
        """Return a local file:// URL (no real expiry for local backend).

        Args:
            key: Relative path within the local export directory.
            expires_in: Ignored for local storage.

        Returns:
            ``file://`` URI string.
        """
        return f'file://{self._root / key}'

    async def delete(self, key: str) -> None:
        """Remove a local export file.

        Args:
            key: Relative path within the local export directory.
        """
        target = self._root / key
        if target.exists():
            target.unlink()
