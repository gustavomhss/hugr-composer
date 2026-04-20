from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class OAuthTokens:
    """Tokens returned from the provider's token endpoint.

    Attributes:
        access_token: Short-lived access token.
        refresh_token: Long-lived refresh token, or None.
        expires_in: Validity in seconds, or None.
        raw: Full provider response payload.
    """
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    raw: dict[str, Any]
