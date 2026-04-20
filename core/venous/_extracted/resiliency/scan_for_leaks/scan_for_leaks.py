from __future__ import annotations


def scan_for_leaks(text: str, known_secrets: list[str]) -> list[str]:
    """Scan *text* for substrings that match *known_secrets*.

    Called by LeakDetectorMiddleware before responses leave the process.
    Never raises — returns an empty list when text is safe.

    Args:
        text: String to scan (response body, log line, error message).
        known_secrets: List of secret values to look for (plaintext).

    Returns:
        List of secret names found in *text* (empty = safe).
    """
    found: list[str] = []
    for secret in known_secrets:
        if secret and len(secret) > 4 and (secret in text):
            found.append(secret[:4] + '***')
    return found
