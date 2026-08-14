"""DeprecationEntry — framework-free metadata for one deprecated endpoint.

Invariants cited here:

- DE_INV_01 — sunset parse: ``sunset`` MUST be an ISO-8601 date
  string. Invalid input raises ``ValueError`` at construction; no
  silent coercion.
- DE_INV_02 — method normalisation: HTTP method is upper-cased on
  ingestion. Downstream comparisons are case-insensitive by
  construction.
- DE_INV_03 — sunset-header shape: ``sunset_header`` returns the
  stored date as an ISO string (RFC 8594 Sunset header compatible).
- DE_INV_04 — warn-window monotone: ``should_warn`` is True iff
  ``days_until_sunset <= warn_days_before_sunset``. Past-sunset
  entries (negative days) always warn.
- DE_INV_05 — serialisable: ``to_dict()`` output is JSON-safe and
  carries every public field + the derived ``days_until_sunset``
  + ``warn`` bool.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

# Default warning window. Caller can override per-entry via
# ``warn_days_before_sunset`` constructor kwarg. Reading from a
# framework-specific `settings` object would couple this primitive
# to FastAPI/pydantic-settings — the motor stays framework-free;
# application glue (app/...) passes the desired window.
_DEFAULT_WARN_DAYS: int = 30


class DeprecationEntry:
    """Metadata for a single deprecated endpoint.

    Attributes:
        path: URL path of the deprecated endpoint.
        method: HTTP method (uppercased).
        sunset_date: Date when the endpoint will be removed.
        replacement: URL of the replacement endpoint.
        description: Optional human-readable deprecation reason.
        warn_days_before_sunset: Window in days before `sunset_date`
            where ``should_warn`` returns True.

    """

    __slots__ = (
        "description",
        "method",
        "path",
        "replacement",
        "sunset_date",
        "warn_days_before_sunset",
    )

    def __init__(
        self,
        path: str,
        method: str,
        sunset: str,
        replacement: str,
        description: str = "",
        *,
        warn_days_before_sunset: int = _DEFAULT_WARN_DAYS,
    ) -> None:
        self.path = path
        self.method = method.upper()
        self.sunset_date = date.fromisoformat(sunset)  # DE_INV_01
        self.replacement = replacement
        self.description = description
        self.warn_days_before_sunset = warn_days_before_sunset

    @property
    def sunset_header(self) -> str:
        """RFC 8594 Sunset header value (ISO date string)."""
        return self.sunset_date.isoformat()

    @property
    def days_until_sunset(self) -> int:
        """Days remaining until sunset (negative if already past)."""
        return (self.sunset_date - datetime.now(UTC).date()).days

    @property
    def should_warn(self) -> bool:
        """True iff within the configured warning window before sunset."""
        return self.days_until_sunset <= self.warn_days_before_sunset

    def to_dict(self) -> dict[str, Any]:
        """Serialise entry to a JSON-safe dict.

        Carries every public field (DE_INV_05): the six constructor
        inputs (path, method, sunset, replacement, description,
        warn_days_before_sunset) plus the two derived values consumers
        care about (days_until_sunset, warn).
        """
        return {
            "path": self.path,
            "method": self.method,
            "sunset": self.sunset_date.isoformat(),
            "replacement": self.replacement,
            "description": self.description,
            "warn_days_before_sunset": self.warn_days_before_sunset,
            "days_until_sunset": self.days_until_sunset,
            "warn": self.should_warn,
        }


__all__ = ["DeprecationEntry"]
