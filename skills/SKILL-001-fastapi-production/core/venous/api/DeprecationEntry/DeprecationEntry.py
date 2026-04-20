from __future__ import annotations
from typing import Any


class DeprecationEntry:
    """Metadata for a single deprecated endpoint.

    Attributes:
        path: URL path of the deprecated endpoint.
        method: HTTP method (GET, POST, etc.).
        sunset: Date when the endpoint will be removed.
        replacement: URL of the replacement endpoint.
        description: Optional human-readable deprecation reason.
    """

    def __init__(self, path: str, method: str, sunset: str, replacement: str, description: str='') -> None:
        """Initialise a deprecation entry.

        Args:
            path: URL path of the deprecated endpoint.
            method: HTTP method (GET, POST, etc.).
            sunset: ISO date string when endpoint will be removed.
            replacement: URL of the replacement endpoint.
            description: Optional human-readable deprecation reason.
        """
        self.path = path
        self.method = method.upper()
        self.sunset_date = date.fromisoformat(sunset)
        self.replacement = replacement
        self.description = description

    @property
    def sunset_header(self) -> str:
        """RFC 8594 Sunset header value (ISO date string).

        Returns:
            ISO date string for the Sunset header.
        """
        return self.sunset_date.isoformat()

    @property
    def days_until_sunset(self) -> int:
        """Number of days until the sunset date.

        Returns:
            Days remaining until sunset (negative if already past).
        """
        return (self.sunset_date - date.today()).days

    @property
    def should_warn(self) -> bool:
        """Return True when within the warning window before sunset.

        Returns:
            True when sunset is within DEPRECATION_WARN_DAYS_BEFORE_SUNSET days.
        """
        warn_days = getattr(settings, 'DEPRECATION_WARN_DAYS_BEFORE_SUNSET', 30)
        return self.days_until_sunset <= warn_days

    def to_dict(self) -> dict[str, Any]:
        """Serialise entry to a JSON-safe dict.

        Returns:
            Dict with path, method, sunset, replacement, days_until_sunset.
        """
        return {'path': self.path, 'method': self.method, 'sunset': self.sunset_date.isoformat(), 'replacement': self.replacement, 'description': self.description, 'days_until_sunset': self.days_until_sunset, 'warn': self.should_warn}
