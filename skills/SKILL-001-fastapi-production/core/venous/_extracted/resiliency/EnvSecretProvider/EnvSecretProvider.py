from __future__ import annotations
import os


class EnvSecretProvider(SecretProvider):
    """Environment-variable-backed secret provider (no external service)."""

    def get(self, name: str, default: str='') -> str:
        """Read secret from environment.

        Args:
            name: Environment variable name.
            default: Fallback value.

        Returns:
            Environment variable value or default.
        """
        return os.environ.get(name, default)

    def set(self, name: str, value: str) -> None:
        """Write secret to the current process environment.

        Note: only affects the running process.  Use your deployment
        tool (Helm, Terraform, etc.) for persistent rotation.

        Args:
            name: Environment variable name.
            value: New value.
        """
        os.environ[name] = value
