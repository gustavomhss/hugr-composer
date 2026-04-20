from __future__ import annotations
from abc import ABC
from abc import abstractmethod


class OAuthProvider(ABC):
    """Abstract interface for an OAuth2 provider.

    Each provider must implement ``authorization_url``, ``exchange_code``,
    and ``fetch_user``.  All implementations use Authorization Code + PKCE.
    """
    name: str

    @abstractmethod
    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        """Build the provider's authorization redirect URL.

        Args:
            state: CSRF state token.
            code_challenge: PKCE S256 challenge string.
            redirect_uri: Callback URL registered with the provider.

        Returns:
            Full authorization URL to redirect the user to.
        """

    @abstractmethod
    async def exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> OAuthTokens:
        """Exchange an authorization code for tokens.

        Args:
            code: Authorization code from the callback query string.
            code_verifier: PKCE verifier matching the earlier challenge.
            redirect_uri: Must match the value used in authorization_url.

        Returns:
            ``OAuthTokens`` with access, refresh, and expiry.

        Raises:
            httpx.HTTPStatusError: If the provider rejects the code.
        """

    @abstractmethod
    async def fetch_user(self, access_token: str) -> OAuthUserInfo:
        """Retrieve normalized user information from the provider.

        Args:
            access_token: Fresh access token from exchange_code.

        Returns:
            ``OAuthUserInfo`` with provider_user_id, email, email_verified, name.

        Raises:
            httpx.HTTPStatusError: If the provider's userinfo endpoint fails.
        """
