from __future__ import annotations
from typing import Any


class DeprecationRegistry:
    """Central registry of all deprecated API endpoints."""

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._entries: dict[str, DeprecationEntry] = {}

    def register(self, path: str, method: str, sunset: str, replacement: str, description: str='') -> DeprecationEntry:
        """Register an endpoint as deprecated.

        Args:
            path: URL path of the deprecated endpoint.
            method: HTTP method (GET, POST, etc.).
            sunset: ISO date string when endpoint will be removed.
            replacement: URL of the replacement endpoint.
            description: Optional human-readable reason.

        Returns:
            The created DeprecationEntry.
        """
        key = f'{method.upper()} {path}'
        entry = DeprecationEntry(path, method, sunset, replacement, description)
        self._entries[key] = entry
        if entry.should_warn:
            logger.warning('Deprecated endpoint %s sunsets in %d days -> %s', key, entry.days_until_sunset, replacement)
        return entry

    def get(self, path: str, method: str) -> DeprecationEntry | None:
        """Look up a deprecation entry by path and method.

        Args:
            path: URL path to look up.
            method: HTTP method to look up.

        Returns:
            DeprecationEntry if found, None otherwise.
        """
        return self._entries.get(f'{method.upper()} {path}')

    def list_all(self) -> list[dict[str, Any]]:
        """Return all registered deprecation entries as serialisable dicts.

        Returns:
            List of entry dicts sorted by sunset date ascending.
        """
        return sorted((e.to_dict() for e in self._entries.values()), key=lambda d: d['sunset'])
