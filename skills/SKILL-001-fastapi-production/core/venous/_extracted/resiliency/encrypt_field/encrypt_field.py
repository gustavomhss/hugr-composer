from __future__ import annotations


def encrypt_field(plaintext: str) -> str:
    """Encrypt *plaintext* with Fernet (lazy import).

    Reads ``settings.COMPLIANCE_ENCRYPTION_KEY``; returns plaintext
    unchanged if the key is empty (non-production fallback).

    Args:
        plaintext: The string value to encrypt.

    Returns:
        Fernet token (URL-safe base64) or original plaintext when key absent.
    """
    key = settings.COMPLIANCE_ENCRYPTION_KEY
    if not key:
        return plaintext
    from cryptography.fernet import Fernet
    return Fernet(key.encode()).encrypt(plaintext.encode()).decode()
