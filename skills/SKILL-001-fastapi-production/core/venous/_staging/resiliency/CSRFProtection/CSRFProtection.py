from __future__ import annotations
from fastapi import Response
import hashlib
import hmac
import secrets
import time


class CSRFProtection:
    """CSRF protection using HMAC-signed tokens (double-submit cookie pattern).

    Tokens are ``{random_hex}.{timestamp}.{hmac_signature}``.

    Args:
        secret_key: Secret used for HMAC signing.
        cookie_name: Cookie name for the CSRF token.
        header_name: Request header name clients must send.
        max_age: Token max age in seconds (default 3600).
    """

    def __init__(self, secret_key: str, cookie_name: str=_DEFAULT_COOKIE_NAME, header_name: str=_DEFAULT_HEADER_NAME, max_age: int=_TOKEN_MAX_AGE_SECONDS) -> None:
        """Initialise CSRFProtection with signing key and config.

        Args:
            secret_key: HMAC signing key (min 32 chars recommended).
            cookie_name: Cookie name for the CSRF token.
            header_name: HTTP header clients must send with the token.
            max_age: Token validity window in seconds.
        """
        self._secret = secret_key.encode()
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.max_age = max_age

    def generate_token(self) -> str:
        """Generate a new HMAC-signed CSRF token.

        Returns:
            Token string ``{random}.{timestamp}.{hmac}``.
        """
        random_part = secrets.token_hex(16)
        timestamp = str(int(time.time()))
        payload = f'{random_part}{_TOKEN_SEPARATOR}{timestamp}'
        sig = self._sign(payload)
        return f'{payload}{_TOKEN_SEPARATOR}{sig}'

    def validate_token(self, token: str) -> bool:
        """Validate a CSRF token: checks signature and expiry.

        Args:
            token: Token string from cookie or header.

        Returns:
            ``True`` if token is valid and not expired.
        """
        parts = token.split(_TOKEN_SEPARATOR)
        if len(parts) != 3:
            return False
        random_part, ts_str, sig = parts
        payload = f'{random_part}{_TOKEN_SEPARATOR}{ts_str}'
        expected_sig = self._sign(payload)
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning('CSRF token signature mismatch')
            return False
        try:
            age = int(time.time()) - int(ts_str)
        except ValueError:
            return False
        if age > self.max_age:
            logger.warning('CSRF token expired (age=%ds)', age)
            return False
        return True

    def get_csrf_cookie(self, response: Response, token: str) -> None:
        """Set the CSRF token as a SameSite=Strict cookie on *response*.

        Args:
            response: Starlette/FastAPI response to attach cookie to.
            token: CSRF token string from ``generate_token()``.
        """
        response.set_cookie(key=self.cookie_name, value=token, httponly=False, samesite='strict', secure=False, max_age=self.max_age)

    def _sign(self, payload: str) -> str:
        """Compute HMAC-SHA256 hex digest for *payload*.

        Args:
            payload: String to sign.

        Returns:
            Hex digest string.
        """
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
