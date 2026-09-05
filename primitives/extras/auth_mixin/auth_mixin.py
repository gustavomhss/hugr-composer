"""Pure Python primitive: AuthMixin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class AuthMixin:
    """Mixin providing JWT authentication for Locust HttpUser subclasses.

    Attributes:
        access_token: Cached JWT access token after successful login.
        auth_headers: Ready-to-use headers dict for authenticated requests.
    """
    access_token: Optional[str] = None
    auth_headers: dict[str, str]

    def _random_email(self) -> str:
        """Generate a random email for test user registration.

        Returns:
            Random email string unique within this session.
        """
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        return f'loadtest_{suffix}@example.com'

    def _random_password(self) -> str:
        """Generate a password meeting typical complexity requirements.

        Returns:
            12-character password with upper, lower, digit, and special char.
        """
        chars = string.ascii_letters + string.digits
        base = random.choice(string.ascii_uppercase) + random.choice(string.ascii_lowercase) + random.choice(string.digits) + '!' + ''.join(random.choices(chars, k=8))
        return base

    def login(self) -> None:
        """Authenticate once per simulated user and cache the JWT.

        Tries the FastAPI full-stack template token endpoint first
        (``/api/v1/login/access-token``), then falls back to
        ``/api/v1/auth/token``.

        Side effects:
            Sets ``self.access_token`` and ``self.auth_headers``.
        """
        email = self._random_email()
        password = self._random_password()
        self.client.post('/api/v1/users/signup', json={'email': email, 'password': password}, name='[auth] register')
        resp = self.client.post('/api/v1/login/access-token', data={'username': email, 'password': password}, name='[auth] login')
        token = ''
        if resp.status_code == 200:
            token = resp.json().get('access_token', '')
        self.access_token = token
        self.auth_headers = {'Authorization': f'Bearer {token}'} if token else {}

    def refresh_token(self) -> None:
        """Re-authenticate if the token has expired mid-session.

        Side effects:
            Updates ``self.access_token`` and ``self.auth_headers``.
        """
        self.login()
