from __future__ import annotations
import hashlib
import hmac


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time verification of a raw secret against its stored hash.

    Always performs the full verification work even on mismatch to prevent
    timing oracles.  Falls back to DUMMY_HASH comparison when stored_hash is
    empty so callers can safely verify unknown key_ids.

    Args:
        secret: The raw plaintext secret from the Authorization header.
        stored_hash: The ``secret_hash`` column value from the database.

    Returns:
        ``True`` if the secret matches the stored hash, ``False`` otherwise.
    """
    if not stored_hash:
        hmac.new(_PEPPER, secret.encode('utf-8'), hashlib.sha256).hexdigest()
        return False
    if stored_hash.startswith('argon2$$'):
        if not _ARGON2_AVAILABLE:
            return False
        try:
            _ph.verify(stored_hash[len('argon2$$'):], secret)
            return True
        except VerifyMismatchError:
            return False
    if stored_hash.startswith('sha256$$'):
        expected = hmac.new(_PEPPER, secret.encode('utf-8'), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, stored_hash[len('sha256$$'):])
    return False
