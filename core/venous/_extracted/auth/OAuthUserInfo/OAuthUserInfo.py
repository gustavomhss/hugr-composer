from __future__ import annotations
from dataclasses import dataclass


@dataclass
class OAuthUserInfo:
    """Normalized user information returned by a provider.

    Attributes:
        provider_user_id: Stable unique identifier from the provider.
        email: Email address reported by the provider.
        email_verified: Whether the provider has verified this email.
        name: Display name, or None if not provided.
    """
    provider_user_id: str
    email: str | None
    email_verified: bool
    name: str | None
