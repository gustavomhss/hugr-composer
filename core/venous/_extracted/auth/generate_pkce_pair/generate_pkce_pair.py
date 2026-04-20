from __future__ import annotations
import base64
import hashlib
import secrets


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE verifier/challenge pair using S256.

    The verifier is 128 URL-safe characters (> 256 bits).  The challenge is
    base64url(SHA-256(verifier)) without trailing ``=`` padding, conforming
    to RFC 7636 §4.2.

    Returns:
        ``(verifier, challenge)`` tuple — send challenge to provider,
        store verifier in Redis state.
    """
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    return (verifier, challenge)
