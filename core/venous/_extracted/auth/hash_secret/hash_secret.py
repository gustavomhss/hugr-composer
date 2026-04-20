from __future__ import annotations
from typing import Literal
import hashlib
import hmac


def hash_secret(secret: str, algorithm: Literal['argon2id', 'sha256_pepper']='sha256_pepper') -> str:
    """Hash a raw API-key secret for safe storage.

    Args:
        secret: The raw plaintext secret to hash.
        algorithm: Hashing algorithm.  ``argon2id`` is GPU-resistant;
            ``sha256_pepper`` is fast with server-side pepper.

    Returns:
        Prefixed hash string (``argon2$$...`` or ``sha256$$...``).

    Raises:
        RuntimeError: If argon2id is requested but argon2-cffi is not installed.
    """
    if algorithm == 'argon2id':
        if not _ARGON2_AVAILABLE:
            raise RuntimeError('argon2-cffi is required for argon2id hashing')
        return 'argon2$$' + _ph.hash(secret)
    digest = hmac.new(_PEPPER, secret.encode('utf-8'), hashlib.sha256).hexdigest()
    return 'sha256$$' + digest
