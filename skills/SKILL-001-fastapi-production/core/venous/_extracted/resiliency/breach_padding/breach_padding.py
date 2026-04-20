from __future__ import annotations
import os
import secrets


def breach_padding(min_bytes: int=0, max_bytes: int=32) -> bytes:
    """Generate random padding bytes to defeat BREACH compression attacks.

    Injects a random-length comment into compressed HTTP responses so
    the attacker cannot infer secret lengths from compressed sizes.

    Args:
        min_bytes: Minimum padding length (default 0).
        max_bytes: Maximum padding length (default 32).

    Returns:
        Random bytes of length between min_bytes and max_bytes.
    """
    length = secrets.randbelow(max(1, max_bytes - min_bytes + 1)) + min_bytes
    return os.urandom(length)
