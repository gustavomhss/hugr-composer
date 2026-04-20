"""MaterializedView primitive — Kleppmann DDIA / Richardson CQRS read model.

Implements the catalog Protocol for `data.MaterializedView` and installs
runtime invariant checkers. Zero I/O at import.

Invariant IDs cited by this module:

- MV-INV-01: apply MUST be deterministic. Given the same event stream in the
  same order, the view state SHALL converge to the same contents.
- MV-INV-02: the view CANNOT be the system of record; rebuild MUST be able to
  regenerate state purely from the source feed.
- MV-INV-03: reads MUST tolerate bounded staleness and NEVER claim
  linearizability with the base data. Staleness is surfaced, not hidden.
- MV-INV-04: schema evolution SHALL trigger a rebuild path; silent backfill
  with stale rows is FORBIDDEN. The view refuses to serve rows produced by a
  prior schema version.
- MV-INV-05: new projections extend MaterializedView by registering handlers
  per aggregate type through the decorator; unknown event types MUST be
  rejected rather than silently dropped into an undefined slot.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, Final, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class MaterializedView(Protocol):
    @property
    def name(self) -> str: ...
    def apply(self, event: Any) -> None: ...
    def rebuild(self, source: Iterable[Any]) -> None: ...
    def query(self, criteria: object) -> Iterable[Any]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class MaterializedViewInvariantError(RuntimeError):
    """Raised when a MaterializedView invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Event shape
# ---------------------------------------------------------------------------
_REQUIRED_EVENT_KEYS: Final[frozenset[str]] = frozenset({"type", "aggregate_id", "seq", "schema_version"})


def _validate_event(event: Mapping[str, object]) -> None:
    missing = _REQUIRED_EVENT_KEYS - set(event.keys())
    if missing:
        raise MaterializedViewInvariantError(
            f"MV-INV-05: event is missing required keys {sorted(missing)}; "
            f"unknown shapes CANNOT be silently dropped into the view."
        )


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MaterializedViewInvariantError(
            f"MV-INV-05: event field '{field}' MUST be a plain int, got {type(value).__name__}."
        )
    return value


def _as_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise MaterializedViewInvariantError(
            f"MV-INV-05: event field '{field}' MUST be a str, got {type(value).__name__}."
        )
    return value


# Handler signature: (view_rows_dict, event) -> None (mutates view in place).
Handler = Callable[[dict[str, dict[str, object]], Mapping[str, object]], None]


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryMaterializedView:
    """Reference MaterializedView.

    Holds a dict of rows keyed by aggregate_id. Applies events via registered
    per-type handlers. Supports `rebuild(source_iterable)` which drops state
    and replays from scratch — the view is NEVER the system of record.

    Staleness is tracked by `last_applied_seq` (monotonic per source stream)
    and `last_applied_at` (monotonic clock). `max_age_s` bounds how stale a
    read may be before the view surfaces `staleness_s()` / `is_fresh()` to
    the caller — callers MUST inspect rather than assume linearizability.

    Schema evolution: each row carries a `schema_version`. If the view's
    declared `schema_version` changes, `query()` refuses until `rebuild()`
    from the source feed has been invoked at the new version.
    """

    def __init__(
        self,
        view_name: str,
        schema_version: int = 1,
        max_age_s: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not view_name or not isinstance(view_name, str):
            raise MaterializedViewInvariantError(
                "MV-INV-02: view_name MUST be a non-empty string identifying this projection."
            )
        self._name = view_name
        self._declared_schema_version = schema_version
        self._materialized_schema_version: int | None = None
        self._max_age_s = max_age_s
        self._clock: Callable[[], float] = clock or time.monotonic

        self._rows: dict[str, dict[str, object]] = {}
        self._handlers: dict[str, Handler] = {}
        self._last_applied_seq: int = -1
        self._last_applied_at: float | None = None
        self._applied_event_count: int = 0
        self._pending_schema_evolution: bool = False
        self._lock = threading.RLock()

    # ----- Protocol surface --------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    def apply(self, event: Any) -> None:
        if not isinstance(event, Mapping):
            raise MaterializedViewInvariantError(
                "MV-INV-05: event MUST be a Mapping; other shapes are rejected rather than silently dropped."
            )
        _validate_event(event)
        etype = _as_str(event["type"], "type")
        evt_schema = _as_int(event["schema_version"], "schema_version")
        seq = _as_int(event["seq"], "seq")

        with self._lock:
            if evt_schema != self._declared_schema_version:
                # MV-INV-04: schema mismatch MUST trigger a rebuild path — no silent backfill.
                raise MaterializedViewInvariantError(
                    f"MV-INV-04: event schema_version={evt_schema} does not match declared "
                    f"schema_version={self._declared_schema_version}; schema evolution "
                    f"SHALL trigger rebuild() — silent backfill is FORBIDDEN."
                )
            if etype not in self._handlers:
                # MV-INV-05: unknown event types MUST be rejected, not silently dropped.
                raise MaterializedViewInvariantError(
                    f"MV-INV-05: no handler registered for event type '{etype}'; "
                    f"unknown events CANNOT be silently applied."
                )
            if seq <= self._last_applied_seq:
                # Out-of-order / duplicate: dedupe so MV-INV-01 (determinism from ordered
                # stream) holds under at-least-once delivery from the source.
                return
            if self._pending_schema_evolution:
                raise MaterializedViewInvariantError(
                    f"MV-INV-04: schema evolution to v{self._declared_schema_version} is pending; "
                    f"rebuild() MUST run before further apply() calls."
                )
            self._handlers[etype](self._rows, event)
            self._last_applied_seq = seq
            self._last_applied_at = self._clock()
            self._applied_event_count += 1
            if self._materialized_schema_version is None:
                self._materialized_schema_version = self._declared_schema_version

    def rebuild(self, source: Iterable[Any]) -> None:
        """Regenerate the view purely from the source feed (MV-INV-02).

        Clears all state and replays every event. All events in the source
        MUST match the view's declared schema_version; mixing versions
        mid-rebuild raises MV-INV-04.
        """
        with self._lock:
            self._rows.clear()
            self._last_applied_seq = -1
            self._last_applied_at = None
            self._applied_event_count = 0
            self._materialized_schema_version = None
            # Until rebuild finishes, the view is in a torn state — queries refuse.
            self._pending_schema_evolution = True

            for event in source:
                if not isinstance(event, Mapping):
                    raise MaterializedViewInvariantError(
                        "MV-INV-05: rebuild source contained a non-Mapping event."
                    )
                _validate_event(event)
                evt_schema = _as_int(event["schema_version"], "schema_version")
                if evt_schema != self._declared_schema_version:
                    raise MaterializedViewInvariantError(
                        f"MV-INV-04: rebuild event schema_version={evt_schema} mismatches "
                        f"declared schema_version={self._declared_schema_version}."
                    )
                etype = _as_str(event["type"], "type")
                if etype not in self._handlers:
                    raise MaterializedViewInvariantError(
                        f"MV-INV-05: rebuild encountered unknown event type '{etype}'."
                    )
                seq = _as_int(event["seq"], "seq")
                if seq <= self._last_applied_seq:
                    # Idempotent replay — duplicates / reordered suffix ignored.
                    continue
                self._handlers[etype](self._rows, event)
                self._last_applied_seq = seq
                self._last_applied_at = self._clock()
                self._applied_event_count += 1
            self._materialized_schema_version = self._declared_schema_version
            self._pending_schema_evolution = False

    def query(self, criteria: object) -> Iterable[Any]:
        """Return rows matching `criteria`.

        MV-INV-03: callers MUST treat results as bounded-stale; callers can
        inspect `staleness_s()` to decide if the read is fresh enough.
        MV-INV-04: if schema evolution is pending (view not rebuilt at the
        declared version), query refuses rather than serve stale rows.
        """
        with self._lock:
            if self._pending_schema_evolution:
                raise MaterializedViewInvariantError(
                    f"MV-INV-04: view '{self._name}' has pending schema evolution to "
                    f"v{self._declared_schema_version}; rebuild() MUST run before query()."
                )
            rows_snapshot = [dict(r) for r in self._rows.values()]

        criteria_map: Mapping[str, object]
        if isinstance(criteria, Mapping):
            criteria_map = criteria
        elif criteria is None:
            criteria_map = {}
        else:
            # Reject shapes we cannot interpret rather than silently returning all rows.
            raise MaterializedViewInvariantError(
                "MV-INV-05: query criteria MUST be a Mapping or None; other shapes are rejected."
            )
        return _filter_rows(rows_snapshot, criteria_map)

    # ----- extension contract ------------------------------------------------
    def on(self, event_type: str) -> Callable[[Handler], Handler]:
        """Decorator registering a handler for `event_type` per aggregate type.

        Extension contract — MV-INV-05. The registered handler receives the
        current rows dict and the event, and is expected to mutate rows
        deterministically so MV-INV-01 holds.
        """
        if not event_type or not isinstance(event_type, str):
            raise MaterializedViewInvariantError(
                "MV-INV-05: event_type MUST be a non-empty string."
            )

        def _decorator(fn: Handler) -> Handler:
            with self._lock:
                if event_type in self._handlers:
                    raise MaterializedViewInvariantError(
                        f"MV-INV-05: handler for '{event_type}' already registered; "
                        f"re-registration would make apply() non-deterministic."
                    )
                self._handlers[event_type] = fn
            return fn

        return _decorator

    def register_handler(self, event_type: str, fn: Handler) -> None:
        """Non-decorator equivalent of `on(event_type)`."""
        self.on(event_type)(fn)

    # ----- introspection for MV-INV-03 (bounded staleness) ------------------
    def staleness_s(self) -> float:
        """Seconds since the last applied event; +inf if nothing applied yet."""
        with self._lock:
            if self._last_applied_at is None:
                return float("inf")
            return max(0.0, self._clock() - self._last_applied_at)

    def is_fresh(self) -> bool:
        """True iff staleness is within the declared max_age_s bound."""
        return self.staleness_s() <= self._max_age_s

    @property
    def last_applied_seq(self) -> int:
        return self._last_applied_seq

    @property
    def applied_event_count(self) -> int:
        return self._applied_event_count

    @property
    def declared_schema_version(self) -> int:
        return self._declared_schema_version

    @property
    def materialized_schema_version(self) -> int | None:
        return self._materialized_schema_version

    @property
    def max_age_s(self) -> float:
        return self._max_age_s

    def evolve_schema(self, new_version: int) -> None:
        """Declare a schema evolution.

        MV-INV-04: query() SHALL refuse until rebuild() is invoked with a
        source feed compatible with `new_version`.
        """
        if not isinstance(new_version, int) or isinstance(new_version, bool) or new_version < 1:
            raise MaterializedViewInvariantError(
                "MV-INV-04: schema_version MUST be a positive int."
            )
        with self._lock:
            self._declared_schema_version = new_version
            self._materialized_schema_version = None
            self._pending_schema_evolution = True

    def rows(self) -> tuple[Mapping[str, object], ...]:
        """Read-only snapshot of rows — test / observability helper."""
        with self._lock:
            return tuple(dict(r) for r in self._rows.values())


# ---------------------------------------------------------------------------
# Query filter helper
# ---------------------------------------------------------------------------
def _filter_rows(
    rows: list[dict[str, object]],
    criteria: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    for row in rows:
        if all(row.get(k) == v for k, v in criteria.items()):
            yield dict(row)


__all__ = [
    "Handler",
    "InMemoryMaterializedView",
    "MaterializedView",
    "MaterializedViewInvariantError",
]
