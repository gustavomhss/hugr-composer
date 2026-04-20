from __future__ import annotations
import hmac


def compare_tokens(a: str, b: str) -> bool:
    """Compare two string tokens in constant time.

    Uses ``hmac.compare_digest`` so the comparison time does not
    reveal how many characters match (timing oracle prevention).

    Args:
        a: First token string.
        b: Second token string (e.g. expected token from storage).

    Returns:
        ``True`` if tokens are equal, ``False`` otherwise.
    """
    try:
        return hmac.compare_digest(a.encode(), b.encode())
    except (AttributeError, TypeError) as exc:
        logger.warning('timing_safe.compare_tokens.type_error', extra={'exc': str(exc)})
        return False
