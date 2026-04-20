"""EventStream primitive — Kleppmann DDIA Ch. 11 / Richardson event logs.

Implements the catalog Protocol for `events.EventStream` and installs runtime
invariant checkers. Zero I/O at import.

Invariant IDs cited by this module:

- ES-INV-01: events MUST be strictly ordered within a partition; cross-partition
  ordering is NEVER guaranteed. Per-partition sequence numbers are assigned
  under the lock at append time and are strictly increasing.
- ES-INV-02: appended events CANNOT be mutated or deleted out of retention
  windows; immutability SHALL be enforced. The returned iterators yield deep
  copies and the underlying storage exposes no mutation API.
- ES-INV-03: consumers MUST be able to start from any valid offset and replay;
  destructive consumption is FORBIDDEN. `read_from()` is idempotent: repeated
  calls at the same offset return the same events.
- ES-INV-04: `truncate_before` ALWAYS obeys the configured retention policy;
  arbitrary backdated truncation is FORBIDDEN. The truncation point can only
  advance, can never exceed head, and must respect the retention floor.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator, Mapping
from typing import Any, Final, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class EventStream(Protocol):
    def append(self, partition_key: str, event: Any) -> int: ...
    def read_from(self, partition_key: str, offset: int) -> Iterator[Any]: ...
    def tail(self, partition_key: str) -> int: ...
    def truncate_before(self, offset: int) -> None: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class EventStreamInvariantError(RuntimeError):
    """Raised when an EventStream invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Type-guard helpers
# ---------------------------------------------------------------------------
def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventStreamInvariantError(
            f"ES-INV-01: field '{field}' MUST be a plain int, got {type(value).__name__}."
        )
    return value


def _check_partition_key(partition_key: object) -> str:
    if not isinstance(partition_key, str) or not partition_key:
        raise EventStreamInvariantError(
            "ES-INV-01: partition_key MUST be a non-empty string."
        )
    return partition_key


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryEventStream:
    """Reference EventStream backed by per-partition append-only lists.

    Each partition owns its own strictly-monotonic sequence (seq) starting at
    1. Positions (seq) are assigned under the per-stream RLock at append time
    so concurrent appenders can never collide on a partition's offset
    (ES-INV-01).

    Events are deep-copied on both ingress and egress so neither the caller
    nor a consumer can mutate in-flight entries on the log (ES-INV-02).

    Retention is modelled by `retention_min_entries`: `truncate_before()` will
    refuse to evict events that would leave fewer than that many entries in
    the partition, and it will refuse to move the truncation cursor backward
    (ES-INV-04). A caller that wants to keep all events sets retention to a
    very large value; a caller that wants strict FIFO eviction sets it to 0.

    `read_from()` returns a snapshot iterator so concurrent appends during
    iteration never cause a consumer to observe torn state; repeated reads at
    the same offset return identical event sequences (ES-INV-03).
    """

    _MAX_PARTITIONS: Final[int] = 10_000
    _MAX_PARTITION_KEY_LEN: Final[int] = 512

    def __init__(self, retention_min_entries: int = 0) -> None:
        if isinstance(retention_min_entries, bool) or not isinstance(retention_min_entries, int):
            raise EventStreamInvariantError(
                "ES-INV-04: retention_min_entries MUST be a plain int."
            )
        if retention_min_entries < 0:
            raise EventStreamInvariantError(
                "ES-INV-04: retention_min_entries MUST be >= 0."
            )
        # Per-partition append-only log of (seq, event) tuples. Never reordered,
        # never mutated in place (ES-INV-01 / ES-INV-02).
        self._logs: dict[str, list[tuple[int, object]]] = {}
        # Per-partition next sequence number; monotonic, starts at 1.
        self._next_seq: dict[str, int] = {}
        # Per-partition highest truncated-before offset; monotonic (ES-INV-04).
        self._truncated_before: dict[str, int] = {}
        # Retention policy — partitions may not be truncated below this many
        # retained entries (ES-INV-04).
        self._retention_min_entries: Final[int] = retention_min_entries
        # RLock protects logs, seq counters, and truncation cursors.
        self._lock = threading.RLock()

    # ----- protocol surface --------------------------------------------------
    def append(self, partition_key: str, event: Any) -> int:
        """Append `event` to the partition; return the assigned monotonic seq.

        ES-INV-01 / ES-INV-02:
        - seq is assigned under the lock → strictly increasing per partition.
        - event is deep-copied on ingress so the caller retains no handle that
          could be used to mutate the stored entry after the fact.
        """
        key = _check_partition_key(partition_key)
        if len(key) > self._MAX_PARTITION_KEY_LEN:
            raise EventStreamInvariantError(
                f"ES-INV-01: partition_key length {len(key)} exceeds "
                f"{self._MAX_PARTITION_KEY_LEN}."
            )
        with self._lock:
            if key not in self._logs and len(self._logs) >= self._MAX_PARTITIONS:
                raise EventStreamInvariantError(
                    f"ES-INV-01: partition count exceeded limit "
                    f"({self._MAX_PARTITIONS}); evict or shard before creating more."
                )
            if key not in self._logs:
                self._logs[key] = []
                self._next_seq[key] = 1
                self._truncated_before[key] = 0
            seq = self._next_seq[key]
            # Deep copy protects the stored payload from later caller mutation.
            stored = copy.deepcopy(event)
            self._logs[key].append((seq, stored))
            self._next_seq[key] = seq + 1
            return seq

    def read_from(self, partition_key: str, offset: int) -> Iterator[Any]:
        """Yield events in `partition_key` whose seq >= offset.

        ES-INV-03: non-destructive. Repeated calls at the same offset return
        the same events. The returned events are deep copies so a consumer
        cannot mutate the log by writing back into the yielded object.

        Reading from a partition that was (partially) truncated is allowed
        only when `offset` is >= the partition's `truncated_before` cursor;
        otherwise the reader would observe a hole and silently lose data.
        """
        key = _check_partition_key(partition_key)
        off = _as_int(offset, "offset")
        if off < 0:
            raise EventStreamInvariantError(
                "ES-INV-03: offset MUST be >= 0 (sequence numbers are positive)."
            )
        with self._lock:
            if key not in self._logs:
                # Reading an unknown partition is an empty stream, not an error.
                # Consumers routinely poll partitions that have not yet seen
                # their first event — raising here would force awkward probing.
                return iter(())
            truncated_before = self._truncated_before[key]
            if off < truncated_before:
                raise EventStreamInvariantError(
                    f"ES-INV-03: offset {off} precedes truncation cursor "
                    f"{truncated_before}; consumers MUST NOT read into an "
                    f"evicted window."
                )
            snapshot = [
                copy.deepcopy(event)
                for (seq, event) in self._logs[key]
                if seq >= off
            ]
        return iter(snapshot)

    def tail(self, partition_key: str) -> int:
        """Return the next-unused seq for `partition_key` (1 when empty).

        This is the position at which the *next* append will land. Readers use
        `tail()` as a high-water mark for replay — iterating `read_from(key, x)`
        up to `tail()` yields exactly the events committed before the call.
        """
        key = _check_partition_key(partition_key)
        with self._lock:
            return self._next_seq.get(key, 1)

    def truncate_before(self, offset: int) -> None:
        """Truncate every partition so that events with seq < `offset` are dropped.

        ES-INV-04:
        - `offset` MUST be a non-negative int.
        - The truncation cursor CANNOT rewind: if a prior call advanced past
          `offset`, this call is rejected.
        - Retention floor: a partition is NEVER truncated below
          `retention_min_entries` retained events.
        - Truncation stops at `tail() - 1`: a caller cannot ask the stream to
          forget events that do not yet exist.
        """
        off = _as_int(offset, "offset")
        if off < 0:
            raise EventStreamInvariantError(
                "ES-INV-04: truncate offset MUST be >= 0."
            )
        with self._lock:
            # Validate against every existing partition BEFORE any mutation so
            # a single bad offset does not leave the stream half-truncated.
            for key, log in self._logs.items():
                prior = self._truncated_before[key]
                if off < prior:
                    raise EventStreamInvariantError(
                        f"ES-INV-04: truncate_before MUST be monotonic; "
                        f"partition {key!r} already truncated to {prior}, "
                        f"rewind to {off} is FORBIDDEN."
                    )
                if off > self._next_seq[key]:
                    raise EventStreamInvariantError(
                        f"ES-INV-04: truncate offset {off} exceeds tail "
                        f"{self._next_seq[key]} for partition {key!r}; "
                        f"backdated truncation is FORBIDDEN."
                    )
                retained = sum(1 for (seq, _e) in log if seq >= off)
                if retained < self._retention_min_entries and log:
                    raise EventStreamInvariantError(
                        f"ES-INV-04: truncate_before({off}) would leave "
                        f"{retained} entries in partition {key!r}, below "
                        f"retention floor {self._retention_min_entries}."
                    )
            # All validations passed — apply truncation atomically.
            for key, log in self._logs.items():
                self._logs[key] = [(seq, e) for (seq, e) in log if seq >= off]
                self._truncated_before[key] = off

    # ----- introspection (testing / observability helpers) ------------------
    @property
    def partition_count(self) -> int:
        with self._lock:
            return len(self._logs)

    def partition_size(self, partition_key: str) -> int:
        """Return number of retained events in a partition (0 if unknown)."""
        key = _check_partition_key(partition_key)
        with self._lock:
            return len(self._logs.get(key, ()))

    def truncated_before_of(self, partition_key: str) -> int:
        """Return the truncation cursor for a partition (0 if unknown)."""
        key = _check_partition_key(partition_key)
        with self._lock:
            return self._truncated_before.get(key, 0)

    def log_snapshot(self, partition_key: str) -> tuple[Mapping[str, object], ...]:
        """Return a deep-copied snapshot of (seq, event) pairs for a partition."""
        key = _check_partition_key(partition_key)
        with self._lock:
            entries = self._logs.get(key, [])
            return tuple(
                {"seq": seq, "event": copy.deepcopy(event)}
                for (seq, event) in entries
            )


# ---------------------------------------------------------------------------
# Transport / adapter extension point (ES-INV-01 ordering preserved across stages)
# ---------------------------------------------------------------------------
class StageAdapter:
    """Minimal processing-stage adapter enforcing the extension contract.

    Processing topologies compose pluggable stages that MUST NOT break
    per-partition order (ES-INV-01). A stage is a pure callable
    `(partition_key, event) -> event`; stages are applied in declaration order
    before the event lands on the underlying `EventStream`. Reordering or
    re-partitioning a stage is FORBIDDEN.
    """

    def __init__(
        self,
        downstream: InMemoryEventStream,
        stages: tuple[object, ...] = (),
    ) -> None:
        self._downstream = downstream
        for stage in stages:
            if not callable(stage):
                raise EventStreamInvariantError(
                    "ES-INV-01: every stage MUST be callable "
                    "(partition_key, event) -> event."
                )
        self._stages = stages

    def publish(self, partition_key: str, event: Any) -> int:
        """Apply every stage in declared order, then append to the downstream log."""
        out: object = event
        for stage in self._stages:
            out = stage(partition_key, out)  # type: ignore[operator]  # callable verified in __init__
        return self._downstream.append(partition_key, out)


__all__ = [
    "EventStream",
    "EventStreamInvariantError",
    "InMemoryEventStream",
    "StageAdapter",
]
