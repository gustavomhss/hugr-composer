from __future__ import annotations


def get_secret_provider() -> SecretProvider:
    """Return the configured SecretProvider singleton.

    Reads ``SECRET_PROVIDER`` env var (vault | aws | env).

    Returns:
        A SecretProvider implementation matching the configured backend.
    """
    from app.core.config import settings
    provider = settings.SECRET_PROVIDER.lower()
    if provider == 'vault':
        return VaultSecretProvider(url=settings.VAULT_URL, token=settings.VAULT_TOKEN)
    if provider == 'aws':
        return AwsSecretProvider()
    return EnvSecretProvider()
