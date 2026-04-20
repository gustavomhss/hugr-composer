"""CardinalityGuard primitive — bounds unique attribute-value combinations.

Invariant IDs:

- CARD-INV-01: at per-metric limit, new attribute combinations MUST collapse to
  a single 'overflow' series; NEVER emitted with originals.
- CARD-INV-02: per-key limit rejects any key whose value has been seen in more
  than N distinct forms in the window.
- CARD-INV-03: default deny-list FORBIDS user identifiers, full URL paths, email
  addresses, freeform query strings as attribute values.
- CARD-INV-04: admission SHALL be deterministic for (metric_name, attributes) in
  a single aggregation window.
- CARD-INV-05: guard NEVER mutates caller's attribute mapping in place; ALWAYS
  returns a new mapping.
- CARD-INV-06: overflow events MUST be observable via a dedicated counter.
- CARD-INV-07: configure CANNOT be invoked after the first admit call.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from typing import Final, Protocol, runtime_checkable

# CARD-INV-03: default deny-list for common unbounded-cardinality keys.
DEFAULT_DENY_KEYS: Final[frozenset[str]] = frozenset(
    {"user.id", "user_id", "enduser.id", "request.id", "request_id",
     "url.full", "http.url", "http.target", "email", "trace_id"}
)
EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CardinalityInvariantError(ValueError):
    """Runtime invariant violation on CardinalityGuard."""


@runtime_checkable
class CardinalityGuard(Protocol):
    def admit(
        self, metric_name: str, attributes: Mapping[str, str]
    ) -> Mapping[str, str]: ...

    def configure(
        self, *, per_metric_limit: int, per_key_limit: int,
        overflow_label: str = "overflow",
    ) -> None: ...

    def stats(self, metric_name: str) -> Mapping[str, int]: ...


class InMemoryCardinalityGuard:
    """Reference CardinalityGuard."""

    def __init__(
        self,
        *,
        per_metric_limit: int = 100,
        per_key_limit: int = 20,
        overflow_label: str = "overflow",
        deny_keys: frozenset[str] = DEFAULT_DENY_KEYS,
    ) -> None:
        self._per_metric_limit = per_metric_limit
        self._per_key_limit = per_key_limit
        self._overflow_label = overflow_label
        # CARD-INV-03: normalize to lowercase so the at-admit check can be
        # case-insensitive regardless of how the operator spelled the list.
        self._deny_keys = frozenset(k.lower() for k in deny_keys)
        self._seen: dict[str, set[tuple[tuple[str, str], ...]]] = {}
        self._per_key: dict[tuple[str, str], set[str]] = {}
        self._overflow_count: dict[str, int] = {}
        self._lock = threading.Lock()
        self._configure_locked = False

    def configure(
        self,
        *,
        per_metric_limit: int,
        per_key_limit: int,
        overflow_label: str = "overflow",
    ) -> None:
        """CARD-INV-07: cannot reconfigure after first admit."""
        with self._lock:
            if self._configure_locked:
                raise CardinalityInvariantError(
                    "CARD-INV-07: configure CANNOT be invoked after the first admit call."
                )
            if per_metric_limit < 1 or per_key_limit < 1:
                raise CardinalityInvariantError("limits MUST be ≥1.")
            self._per_metric_limit = per_metric_limit
            self._per_key_limit = per_key_limit
            self._overflow_label = overflow_label

    def admit(
        self, metric_name: str, attributes: Mapping[str, str]
    ) -> Mapping[str, str]:
        with self._lock:
            self._configure_locked = True
            # CARD-INV-05: return a new mapping; do not mutate input.
            clean: dict[str, str] = {}
            for k, v in attributes.items():
                # CARD-INV-03: deny-list is case-insensitive — attackers can
                # otherwise bypass the guard by capitalizing a denied key
                # (e.g. `USER.ID` when the denylist stores `user.id`).
                if k.lower() in self._deny_keys or EMAIL_PATTERN.match(str(v)):
                    clean[k] = self._overflow_label
                    continue
                clean[k] = v

            # CARD-INV-02: per-key cardinality cap.
            for k, v in list(clean.items()):
                key = (metric_name, k)
                seen_vals = self._per_key.setdefault(key, set())
                if v != self._overflow_label and v not in seen_vals:
                    if len(seen_vals) >= self._per_key_limit:
                        clean[k] = self._overflow_label
                    else:
                        seen_vals.add(v)

            # CARD-INV-01: per-metric series cap.
            fingerprint = tuple(sorted(clean.items()))
            series = self._seen.setdefault(metric_name, set())
            if fingerprint not in series:
                if len(series) >= self._per_metric_limit:
                    self._overflow_count[metric_name] = (
                        self._overflow_count.get(metric_name, 0) + 1
                    )
                    return {self._overflow_label: self._overflow_label}
                series.add(fingerprint)

            return clean

    def stats(self, metric_name: str) -> Mapping[str, int]:
        with self._lock:
            return {
                "series": len(self._seen.get(metric_name, set())),
                "overflow_events": self._overflow_count.get(metric_name, 0),
            }


__all__ = [
    "DEFAULT_DENY_KEYS",
    "EMAIL_PATTERN",
    "CardinalityGuard",
    "CardinalityInvariantError",
    "InMemoryCardinalityGuard",
]
