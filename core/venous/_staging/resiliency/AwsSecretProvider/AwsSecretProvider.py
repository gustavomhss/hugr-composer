from __future__ import annotations
from typing import Any


class AwsSecretProvider(SecretProvider):
    """AWS Secrets Manager provider (lazy boto3 import)."""

    def __init__(self, region_name: str='us-east-1') -> None:
        """Initialise AWS SM client.

        Args:
            region_name: AWS region (default 'us-east-1').
        """
        self._region = region_name
        self._client: Any = None

    def _sm(self) -> Any:
        """Return initialised boto3 SecretsManager client (lazy import).

        Returns:
            boto3 secrets manager client.
        """
        if self._client is None:
            import boto3
            self._client = boto3.client('secretsmanager', region_name=self._region)
        return self._client

    def get(self, name: str, default: str='') -> str:
        """Read a secret from AWS Secrets Manager.

        Args:
            name: Secret name / ARN.
            default: Value returned when the secret is missing.

        Returns:
            Secret value string or default.
        """
        try:
            resp = self._sm().get_secret_value(SecretId=name)
            return resp.get('SecretString', default)
        except Exception as exc:
            logger.warning('aws_sm_get_failed', extra={'name': name, 'error': str(exc)})
            return default

    def set(self, name: str, value: str) -> None:
        """Write a secret to AWS Secrets Manager.

        Args:
            name: Secret name.
            value: New secret value.
        """
        try:
            self._sm().put_secret_value(SecretId=name, SecretString=value)
        except Exception as exc:
            logger.error('aws_sm_set_failed', extra={'name': name, 'error': str(exc)})
