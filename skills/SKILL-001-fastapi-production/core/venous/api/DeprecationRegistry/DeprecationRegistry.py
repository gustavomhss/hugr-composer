"""DeprecationRegistry — central registry of deprecated API endpoints.

Invariants cited here:

- DR_INV_01 — key uniqueness: ``(method.upper(), path)`` is the
  composite key; re-registering the same pair replaces the prior
  entry (no silent duplicate accumulation).
- DR_INV_02 — method case-insensitivity: ``get("/p", "get")`` and
  ``get("/p", "GET")`` return the same entry.
- DR_INV_03 — warn-on-register: entries whose ``should_warn`` is
  True emit a logger.warning at registration for ops visibility.
  Absence of warning = not inside the warn window.
- DR_INV_04 — list_all sort order: entries in ``list_all()`` are
  sorted by sunset date ascending (nearest sunset first, so an
  admin dashboard surfaces urgent deprecations at the top).
"""
from __future__ import annotations

import logging
from typing import Any

# Works both for tests (sys.path injection by conftest.py → bare name)
# and for normal package consumers (fully-qualified path).
try:  # pragma: no cover — import shim
    from DeprecationEntry import DeprecationEntry  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — import shim
    from core.venous.api.DeprecationEntry.DeprecationEntry import DeprecationEntry

_logger = logging.getLogger(__name__)


class DeprecationRegistry:
    """Central registry of all deprecated API endpoints."""

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[str, DeprecationEntry] = {}

    def register(
        self,
        path: str,
        method: str,
        sunset: str,
        replacement: str,
        description: str = "",
    ) -> DeprecationEntry:
        """Register an endpoint as deprecated; return the created entry."""
        key = f"{method.upper()} {path}"
        entry = DeprecationEntry(path, method, sunset, replacement, description)
        self._entries[key] = entry
        if entry.should_warn:
            _logger.warning(
                "Deprecated endpoint %s sunsets in %d days -> %s",
                key, entry.days_until_sunset, replacement,
            )
        return entry

    def get(self, path: str, method: str) -> DeprecationEntry | None:
        """Look up a deprecation entry by path and method."""
        return self._entries.get(f"{method.upper()} {path}")

    def list_all(self) -> list[dict[str, Any]]:
        """Return all entries as dicts sorted by sunset date ascending."""
        return sorted(
            (e.to_dict() for e in self._entries.values()),
            key=lambda d: d["sunset"],
        )


__all__ = ["DeprecationRegistry"]
