from __future__ import annotations
import hashlib


def bucket_for_user(flag_key: str, user_id: str) -> int:
    """Deterministic 0..99 bucket via SHA-256 of (flag_key | user_id).

    Args:
        flag_key: Flag key string.
        user_id: User UUID as string.

    Returns:
        Integer in range [0, 99].

    Raises:
        ValueError: If flag_key or user_id is empty.
    """
    if not flag_key or not user_id:
        raise ValueError('flag_key and user_id must be non-empty')
    payload = f'{flag_key}|{user_id}'.encode('utf-8')
    digest = hashlib.sha256(payload).digest()
    bucket_int = int.from_bytes(digest[:4], byteorder='big', signed=False)
    return bucket_int % 100
