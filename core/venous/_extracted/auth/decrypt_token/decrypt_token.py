from __future__ import annotations


def decrypt_token(ciphertext: bytes | None) -> str | None:
    """Decrypt a Fernet-encrypted provider token.

    Args:
        ciphertext: Encrypted bytes from the database, or None.

    Returns:
        Decrypted plaintext string, or ``None`` if input is None or decryption fails.
    """
    if ciphertext is None:
        return None
    try:
        return _get_fernet().decrypt(ciphertext).decode('utf-8')
    except Exception:
        return None
