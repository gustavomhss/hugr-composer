from __future__ import annotations
from pathlib import Path
import asyncio
import os
import uuid


class LocalStorage(StorageBackend):
    """Local filesystem storage with atomic temp-file rename (no partial writes).

    Attributes:
        base_dir: Resolved absolute path to the upload root directory.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, file_obj: object, content_type: str) -> tuple[str, int]:
        """Write *file_obj* atomically to ``base_dir/{uuid}.bin``.

        Args:
            file_obj: Readable file-like object.
            content_type: MIME type (stored in FileMetadata, not in filename).

        Returns:
            ``(stored_key, size_bytes)`` where stored_key is ``"{uuid}.bin"``.
        """
        key = str(uuid.uuid4()) + '.bin'
        target = self.base_dir / key

        def _write() -> int:
            size = 0
            fd, tmp_path = tempfile.mkstemp(dir=self.base_dir)
            try:
                with os.fdopen(fd, 'wb') as fh:
                    while True:
                        chunk = file_obj.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        fh.write(chunk)
                        size += len(chunk)
                os.replace(tmp_path, target)
            except Exception:
                os.unlink(tmp_path)
                raise
            return size
        size = await asyncio.to_thread(_write)
        return (key, size)

    async def get_url(self, stored_key: str, expires_in: int=3600) -> str:
        """Return absolute filesystem path — validate against base_dir (no traversal).

        Args:
            stored_key: UUID-based storage key.
            expires_in: Ignored for local storage.

        Returns:
            Absolute path string.

        Raises:
            ValueError: If stored_key escapes the base_dir.
        """
        target = (self.base_dir / stored_key).resolve()
        if not str(target).startswith(str(self.base_dir)):
            raise ValueError(f'Path traversal attempt rejected: {stored_key}')
        return str(target)

    async def delete(self, stored_key: str) -> None:
        """Delete the file identified by *stored_key* from local storage.

        Args:
            stored_key: UUID-based storage key.
        """
        target = (self.base_dir / stored_key).resolve()
        if not str(target).startswith(str(self.base_dir)):
            raise ValueError(f'Path traversal attempt rejected: {stored_key}')
        target.unlink(missing_ok=True)
