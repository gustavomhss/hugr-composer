from __future__ import annotations
import os
import secrets


class SocialAuthProvider:
    """OAuth2 social login provider.

    Handles authorization URL generation and token exchange for
    Google, GitHub, and Apple. Uses lazy httpx import so the app
    boots without the library installed.

    Args:
        provider: Provider name (google, github, apple).
    """

    def __init__(self, provider: str) -> None:
        """Initialize provider.

        Args:
            provider: One of 'google', 'github', 'apple'.
        """
        self._config = get_provider_config(provider)
        self._provider = provider

    def build_authorization_url(self, redirect_uri: str) -> tuple[str, str]:
        """Build the provider's OAuth2 authorization redirect URL.

        Args:
            redirect_uri: Callback URL registered with the provider.

        Returns:
            Tuple of (authorization_url, state_token).
        """
        state = secrets.token_urlsafe(32)
        client_id = os.environ.get(f'{self._provider.upper()}_CLIENT_ID', '')
        params: dict[str, str] = {'client_id': client_id, 'redirect_uri': redirect_uri, 'scope': ' '.join(self._config.scopes), 'state': state, 'response_type': 'code'}
        if self._provider == 'google':
            params['access_type'] = 'offline'
            params['prompt'] = 'consent'
        if self._provider == 'apple':
            params['response_mode'] = 'form_post'
        url = f'{self._config.auth_url}?{urlencode(params)}'
        return (url, state)

    async def exchange_code(self, code: str, redirect_uri: str) -> SocialUserInfo:
        """Exchange an authorization code for user info.

        Calls the provider's token endpoint then userinfo endpoint.
        httpx is imported lazily inside this method.

        Args:
            code: Authorization code from the callback query string.
            redirect_uri: Must match the value used in build_authorization_url.

        Returns:
            ``SocialUserInfo`` with normalized user data.

        Raises:
            ValueError: If the provider returns an error.
        """
        import httpx
        client_id = os.environ.get(f'{self._provider.upper()}_CLIENT_ID', '')
        client_secret = os.environ.get(f'{self._provider.upper()}_CLIENT_SECRET', '')
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_data = await _fetch_token(client, self._config.token_url, client_id, client_secret, code, redirect_uri, self._provider)
            access_token = token_data.get('access_token', '')
            if self._provider == 'apple':
                return _parse_apple_id_token(token_data, self._provider)
            return await _fetch_userinfo(client, self._config.userinfo_url, access_token, self._provider)
