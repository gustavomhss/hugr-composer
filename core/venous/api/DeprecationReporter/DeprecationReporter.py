"""DeprecationReporter — in-memory tracker for deprecated endpoint call counts.

Invariants cited here:

- DP_INV_01 — monotonic counter: ``record`` only ever increments; no
  path inside this primitive decrements a count other than via an
  explicit ``reset()``.
- DP_INV_02 — method case-insensitivity: counts indexed by
  ``(method.upper(), path)``. ``record("/p", "get")`` and
  ``record("/p", "GET")`` increment the same counter.
- DP_INV_03 — report order: ``usage_report()`` returns entries sorted
  by ``call_count`` descending. Ties broken by insertion order.
- DP_INV_04 — reset completeness: ``reset()`` clears every counter in
  a single call; subsequent ``get_count`` returns 0 for any path.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

_logger = logging.getLogger(__name__)


class DeprecationReporter:
    """In-memory tracker for deprecated endpoint call counts."""

    __slots__ = ("_counts",)

    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    def record(self, path: str, method: str) -> None:
        """Increment call count for a deprecated endpoint."""
        key = f"{method.upper()} {path}"
        self._counts[key] += 1
        _logger.debug(
            "Deprecated endpoint called: %s (total: %d)",
            key, self._counts[key],
        )

    def get_count(self, path: str, method: str) -> int:
        """Return call count for a specific deprecated endpoint (0 if unseen)."""
        return self._counts.get(f"{method.upper()} {path}", 0)

    def usage_report(self) -> list[dict[str, Any]]:
        """Return usage report sorted by call count descending."""
        return sorted(
            [
                {"endpoint": endpoint, "call_count": count}
                for endpoint, count in self._counts.items()
            ],
            key=lambda d: d["call_count"],
            reverse=True,
        )

    def reset(self) -> None:
        """Reset all call counts (for testing / rollover scenarios)."""
        self._counts.clear()


__all__ = ["DeprecationReporter"]
