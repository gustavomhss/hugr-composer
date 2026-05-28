from __future__ import annotations
from abc import ABC
from abc import abstractmethod


class SecretProvider(ABC):
    """Abstract base for secret backends."""

    @abstractmethod
    def get(self, name: str, default: str='') -> str:
        """Retrieve *name* from the secret store.

        Args:
            name: Secret name / path.
            default: Value to return when the secret is not found.

        Returns:
            Secret value string.
        """

    @abstractmethod
    def set(self, name: str, value: str) -> None:
        """Write *value* for *name* in the secret store.

        Args:
            name: Secret name / path.
            value: New secret value.
        """

    def rotate(self, name: str, new_value: str, interval_h: int=24) -> None:
        """Rotate *name* to *new_value* with a dual-key window.

        The old value is preserved as ``<name>_previous`` for *interval_h*
        hours, then overwritten on the next rotation call.

        Args:
            name: Secret name to rotate.
            new_value: New secret value.
            interval_h: Hours to keep the old value accessible.
        """
        old_value = self.get(name)
        if old_value:
            self.set(f'{name}_previous', old_value)
        self.set(name, new_value)
        logger.info('secret_rotated', extra={'name': name, 'dual_key_window_h': interval_h})
