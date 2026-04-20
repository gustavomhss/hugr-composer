from __future__ import annotations
from typing import Any


class VaultSecretProvider(SecretProvider):
    """HashiCorp Vault KV v2 provider (lazy hvac import)."""

    def __init__(self, url: str, token: str, mount_point: str='secret') -> None:
        """Initialise Vault client.

        Args:
            url: Vault server URL.
            token: Vault authentication token.
            mount_point: KV v2 mount path (default 'secret').
        """
        self._url = url
        self._token = token
        self._mount = mount_point
        self._client: Any = None

    def _vault(self) -> Any:
        """Return initialised hvac.Client (lazy import).

        Returns:
            Authenticated hvac client instance.
        """
        if self._client is None:
            import hvac
            self._client = hvac.Client(url=self._url, token=self._token)
        return self._client

    def get(self, name: str, default: str='') -> str:
        """Read a secret from Vault KV v2.

        Args:
            name: Secret path (without mount prefix).
            default: Value returned when the path is missing.

        Returns:
            Secret value or default.
        """
        try:
            resp = self._vault().secrets.kv.v2.read_secret_version(path=name, mount_point=self._mount)
            return resp['data']['data'].get('value', default)
        except Exception as exc:
            logger.warning('vault_get_failed', extra={'name': name, 'error': str(exc)})
            return default

    def set(self, name: str, value: str) -> None:
        """Write a secret to Vault KV v2.

        Args:
            name: Secret path.
            value: New secret value.
        """
        try:
            self._vault().secrets.kv.v2.create_or_update_secret(path=name, secret={'value': value}, mount_point=self._mount)
        except Exception as exc:
            logger.error('vault_set_failed', extra={'name': name, 'error': str(exc)})
