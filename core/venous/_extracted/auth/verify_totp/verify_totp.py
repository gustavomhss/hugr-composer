from __future__ import annotations


def verify_totp(secret: str, code: str, valid_window: int | None=None) -> bool:
    """Verify a 6-digit TOTP code against *secret* with drift tolerance.

    Uses ``hmac.compare_digest`` internally (via pyotp) for constant-time
    comparison.

    Args:
        secret: Plaintext base32 TOTP secret.
        code: 6-digit code from the authenticator app.
        valid_window: Number of ±steps to accept (default from settings).

    Returns:
        ``True`` if the code is valid within the tolerance window.
    """
    if not code or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window if valid_window is not None else _WINDOW)
