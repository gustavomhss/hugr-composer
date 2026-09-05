"""OAuth provider base."""

from __future__ import annotations
from abc import ABC, abstractmethod

class OAuthProvider(ABC):
    """Base class for OAuth providers."""

    @abstractmethod
    def get_authorization_url(self, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str) -> dict: ...
