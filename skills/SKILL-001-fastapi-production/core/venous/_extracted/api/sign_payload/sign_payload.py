from __future__ import annotations
import hashlib
import hmac
import time


def sign_payload(secret: str, body: bytes, timestamp: int | None=None) -> SignatureHeader:
    """Compute a Stripe-style HMAC-SHA256 signature header.

    Args:
        secret: The endpoint's signing secret.
        body: The raw JSON request body bytes.
        timestamp: Unix seconds override (defaults to current time).

    Returns:
        A ``SignatureHeader`` with the computed MAC.

    Raises:
        ValueError: If *secret* is empty.
    """
    if not secret:
        raise ValueError('secret must be non-empty')
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f'{ts}.'.encode('utf-8') + body
    mac = hmac.new(secret.encode('utf-8'), signed_payload, hashlib.sha256).hexdigest()
    return SignatureHeader(timestamp=ts, v1_hex=mac)
