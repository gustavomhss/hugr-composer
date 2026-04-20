from __future__ import annotations
import os


def get_storage() -> S3StorageBackend | LocalStorageBackend:
    """Factory — returns backend configured by ``STORAGE_BACKEND`` env var.

    Returns:
        Configured storage backend instance.

    Raises:
        NotImplementedError: If ``STORAGE_BACKEND`` is set to an unknown value.
    """
    backend = os.getenv('STORAGE_BACKEND', 'local')
    if backend == 's3':
        return S3StorageBackend()
    if backend == 'local':
        return LocalStorageBackend()
    raise NotImplementedError(f'Storage backend {backend!r} not implemented.')
