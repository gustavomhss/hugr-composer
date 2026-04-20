from __future__ import annotations


def decrypt_secret(blob: bytes, *, _f: Fernet | None=None) -> str | None:
    """Decrypt a Fernet-encrypted TOTP secret.

    Args:
        blob: Encrypted byte blob from ``encrypt_secret``.
        _f: Optional Fernet override (for tests).

    Returns:
        Plaintext base32 TOTP secret, or ``None`` on decryption failure.
    """
    f = _f or _fernet
    if f is None:
        raise RuntimeError('MFA_FERNET_KEY is not configured')
    try:
        return f.decrypt(blob).decode('utf-8')
    except InvalidToken:
        return None
