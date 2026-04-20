from __future__ import annotations
import hmac
import time


def verify_signature(secret: str, body: bytes, header_value: str, now: int | None=None) -> bool:
    """Constant-time verify with replay-window check.

    Args:
        secret: The shared signing secret.
        body: The raw request body bytes.
        header_value: The ``X-Signature`` header value to verify.
        now: Current Unix seconds override (defaults to ``time.time()``).

    Returns:
        ``True`` if the signature is valid and within the replay window.
    """
    header = parse_signature_header(header_value)
    if header is None:
        return False
    now_ts = now if now is not None else int(time.time())
    if abs(now_ts - header.timestamp) > MAX_SIGNATURE_AGE_SECONDS:
        return False
    expected = sign_payload(secret, body, header.timestamp)
    return hmac.compare_digest(expected.v1_hex, header.v1_hex)
