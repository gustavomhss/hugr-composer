"""EventSourcedStore primitive — Fowler / Vernon / Richardson event sourcing.

Implements the catalog Protocol for `events.EventSourcedStore` and installs
runtime invariant checkers. Zero I/O at import.

An EventSourcedStore persists each aggregate's state as an ordered sequence of
domain events. The current state of an aggregate is reconstructed by replaying
(``load()`` and folding) those events. Writers call ``append()`` with an
``expected_version`` taken from the previous load; the store uses that token to
implement optimistic concurrency — a conflicting append fails loudly instead of
silently clobbering another writer's events (last-writer-wins is FORBIDDEN).

Invariant IDs cited by this module:

- ESS-INV-01: ``append`` MUST fail with a concurrency error when
  ``expected_version`` does not match the aggregate's current tail; last-writer
  -wins is FORBIDDEN.
- ESS-INV-02: events already written CANNOT be mutated; corrections SHALL be
  expressed as new, compensating events appended with the correct expected
  version.
- ESS-INV-03: snapshots MUST be reproducible from the event log; the store
  NEVER treats a snapshot as the source of truth — a snapshot is an optimisation
  whose correctness is validated against a fold over the events up to the
  snapshot's version.
- ESS-INV-04: replays from version zero ALWAYS produce the same logical state
  given the same event sequence; non-determinism is FORBIDDEN. ``load()`` yields
  events in strict ascending version order, and stored events are deep-copied
  on ingress and egress so the fold is a pure function of the log.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Final, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class EventSourcedStore(Protocol):
    def load(self, aggregate_id: str) -> Iterable[Any]: ...
    def append(
        self,
        aggregate_id: str,
        expected_version: int,
        events: Iterable[Any],
    ) -> int: ...
    def snapshot(self, aggregate_id: str, version: int, state: Any) -> None: ...
    def latest_snapshot(self, aggregate_id: str) -> Any: ...


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------
class EventSourcedStoreInvariantError(RuntimeError):
    """Raised when an EventSourcedStore invariant is violated at runtime."""


class ConcurrencyError(EventSourcedStoreInvariantError):
    """Raised when ``append``'s ``expected_version`` does not match the tail.

    ESS-INV-01: the writer's view of the aggregate is stale; the caller MUST
    re-load and re-apply the command rather than blindly retrying.
    """

    def __init__(
        self,
        aggregate_id: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        super().__init__(
            f"ESS-INV-01: concurrency conflict on aggregate {aggregate_id!r}; "
            f"expected_version={expected_version}, actual_version={actual_version}; "
            f"last-writer-wins is FORBIDDEN — reload and retry."
        )
        self.aggregate_id: Final[str] = aggregate_id
        self.expected_version: Final[int] = expected_version
        self.actual_version: Final[int] = actual_version


# ---------------------------------------------------------------------------
# Type-guard helpers
# ---------------------------------------------------------------------------
def _check_aggregate_id(aggregate_id: object) -> str:
    if not isinstance(aggregate_id, str) or not aggregate_id:
        raise EventSourcedStoreInvariantError(
            "ESS-INV-01: aggregate_id MUST be a non-empty string."
        )
    return aggregate_id


def _as_int(value: object, field: str) -> int:
    # bool is an int subclass in Python — reject it explicitly to avoid
    # accidental True/False sneaking in as version numbers.
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventSourcedStoreInvariantError(
            f"ESS-INV-01: field {field!r} MUST be a plain int, got "
            f"{type(value).__name__}."
        )
    return value


# ---------------------------------------------------------------------------
# Snapshot record (immutable view)
# ---------------------------------------------------------------------------
class SnapshotRecord:
    """Immutable snapshot handle returned by ``latest_snapshot()``.

    Snapshots are read-only handles: mutating the returned ``state`` must not
    affect the store's copy (ESS-INV-03). The store deep-copies on ingress and
    egress so callers CANNOT smuggle a reference that retroactively edits the
    snapshot.
    """

    __slots__ = ("_aggregate_id", "_state", "_version")

    def __init__(self, aggregate_id: str, version: int, state: object) -> None:
        self._aggregate_id: Final[str] = aggregate_id
        self._version: Final[int] = version
        self._state: Final[object] = state

    @property
    def aggregate_id(self) -> str:
        return self._aggregate_id

    @property
    def version(self) -> int:
        return self._version

    @property
    def state(self) -> object:
        # Deep-copy on egress so a caller who mutates the returned state CANNOT
        # pollute the stored snapshot (ESS-INV-03).
        return copy.deepcopy(self._state)

    def __repr__(self) -> str:
        return (
            f"SnapshotRecord(aggregate_id={self._aggregate_id!r}, "
            f"version={self._version})"
        )


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryEventSourcedStore:
    """Reference EventSourcedStore backed by per-aggregate append-only lists.

    The store maintains, for each ``aggregate_id``:

    - an append-only list of events (the source of truth), where the event at
      index ``i`` has logical version ``i + 1`` — versions start at 1 and are
      strictly monotonic;
    - an optional ``SnapshotRecord`` pointing to a version ``v`` such that the
      fold over events ``[1..v]`` yields the snapshot's ``state``.

    All mutation paths hold a reentrant lock so concurrent appenders cannot
    collide on version assignment (ESS-INV-01). Events are deep-copied on
    ingress and egress so neither the caller nor a consumer can mutate in-place
    entries on the log (ESS-INV-02) or retroactively edit a snapshot
    (ESS-INV-03). ``load()`` produces events in strict ascending version order
    so replays are deterministic (ESS-INV-04).
    """

    _MAX_AGGREGATES: Final[int] = 100_000
    _MAX_AGGREGATE_ID_LEN: Final[int] = 512

    def __init__(self) -> None:
        # Per-aggregate append-only event log. Index i holds the event at
        # version i+1. Never reordered, never mutated in place.
        self._events: dict[str, list[object]] = {}
        # Per-aggregate latest snapshot (optional).
        self._snapshots: dict[str, SnapshotRecord] = {}
        # Lock protects the event logs and the snapshot table.
        self._lock = threading.RLock()

    # ----- protocol surface --------------------------------------------------
    def load(self, aggregate_id: str) -> Iterable[Any]:
        """Yield every event for ``aggregate_id`` in ascending version order.

        ESS-INV-04: the returned iterator is a snapshot so concurrent appenders
        during iteration cannot cause a consumer to observe a torn or reordered
        event sequence. Events are deep-copied on egress so a consumer that
        mutates the yielded object CANNOT pollute the stored log (ESS-INV-02).
        Loading an unknown aggregate yields an empty iterator (the conventional
        shape for a fresh aggregate whose first event has not yet been
        persisted).
        """
        key = _check_aggregate_id(aggregate_id)
        with self._lock:
            events = self._events.get(key, [])
            # Deep copy each event on egress and materialise the list under the
            # lock so the caller's iteration is not invalidated by concurrent
            # appends.
            materialised = [copy.deepcopy(e) for e in events]
        return iter(materialised)

    def load_from(self, aggregate_id: str, from_version: int) -> Iterable[Any]:
        """Yield events strictly AFTER ``from_version``.

        Companion to :meth:`load` that avoids materialising the entire
        aggregate history just to discard it. Use with snapshots:
        ``snap + load_from(id, snap.version)`` replays only the tail.

        Version numbering is 1-indexed; ``from_version=0`` is equivalent to
        :meth:`load`. ``from_version`` beyond the tail yields empty.
        """
        key = _check_aggregate_id(aggregate_id)
        if not isinstance(from_version, int) or isinstance(from_version, bool):
            raise EventSourcedStoreError(
                f"load_from: from_version MUST be int, got {type(from_version).__name__}."
            )
        if from_version < 0:
            raise EventSourcedStoreError(
                f"load_from: from_version MUST be >= 0, got {from_version}."
            )
        with self._lock:
            events = self._events.get(key, [])
            tail = events[from_version:]
            materialised = [copy.deepcopy(e) for e in tail]
        return iter(materialised)

    def append(
        self,
        aggregate_id: str,
        expected_version: int,
        events: Iterable[Any],
    ) -> int:
        """Append ``events`` to ``aggregate_id``; return the new tail version.

        ESS-INV-01: ``expected_version`` MUST equal the aggregate's current
        version (its tail). If not, ``ConcurrencyError`` is raised and NO
        events are appended — the append is all-or-nothing.

        ESS-INV-02: stored events are deep copies; the caller's reference is
        NOT retained, so later caller-side mutation cannot rewrite history.

        Appending an empty batch is allowed and is a no-op: it returns the
        current tail version when the expected_version matches. Callers who
        need the write-path to reject empty batches should enforce that at
        their own layer — the store remains composable.
        """
        key = _check_aggregate_id(aggregate_id)
        if len(key) > self._MAX_AGGREGATE_ID_LEN:
            raise EventSourcedStoreInvariantError(
                f"ESS-INV-01: aggregate_id length {len(key)} exceeds "
                f"{self._MAX_AGGREGATE_ID_LEN}."
            )
        expected = _as_int(expected_version, "expected_version")
        if expected < 0:
            raise EventSourcedStoreInvariantError(
                "ESS-INV-01: expected_version MUST be >= 0 (versions start at 0 "
                "for an aggregate with no events)."
            )
        # Materialise the iterable OUTSIDE the lock so an iterable whose
        # production blocks (or raises) never holds the store lock.
        new_events = list(events)
        # Deep-copy on ingress so the caller's reference cannot be used to
        # mutate the stored event after the fact (ESS-INV-02).
        stored_batch = [copy.deepcopy(e) for e in new_events]
        with self._lock:
            if key not in self._events and len(self._events) >= self._MAX_AGGREGATES:
                raise EventSourcedStoreInvariantError(
                    f"ESS-INV-01: aggregate count exceeded limit "
                    f"({self._MAX_AGGREGATES}); shard or evict before adding more."
                )
            log = self._events.setdefault(key, [])
            actual = len(log)
            if expected != actual:
                raise ConcurrencyError(
                    aggregate_id=key,
                    expected_version=expected,
                    actual_version=actual,
                )
            log.extend(stored_batch)
            return len(log)

    def snapshot(self, aggregate_id: str, version: int, state: Any) -> None:
        """Record a snapshot of ``state`` at ``version`` for ``aggregate_id``.

        ESS-INV-03: snapshots are an OPTIMISATION on top of the event log; they
        CANNOT out-run the log (``version`` MUST be <= current tail version) and
        CANNOT rewind (a later snapshot at an older version is rejected). The
        store deep-copies ``state`` on ingress so mutation of the caller's
        object cannot corrupt the stored snapshot.
        """
        key = _check_aggregate_id(aggregate_id)
        ver = _as_int(version, "version")
        if ver < 0:
            raise EventSourcedStoreInvariantError(
                "ESS-INV-03: snapshot version MUST be >= 0."
            )
        with self._lock:
            tail = len(self._events.get(key, []))
            if ver > tail:
                raise EventSourcedStoreInvariantError(
                    f"ESS-INV-03: snapshot version {ver} exceeds aggregate "
                    f"tail {tail}; a snapshot CANNOT out-run the event log."
                )
            prior = self._snapshots.get(key)
            if prior is not None and ver < prior.version:
                raise EventSourcedStoreInvariantError(
                    f"ESS-INV-03: snapshot version {ver} rewinds prior "
                    f"snapshot version {prior.version}; rewind is FORBIDDEN."
                )
            self._snapshots[key] = SnapshotRecord(
                aggregate_id=key,
                version=ver,
                state=copy.deepcopy(state),
            )

    def latest_snapshot(self, aggregate_id: str) -> Any:
        """Return the latest ``SnapshotRecord`` for ``aggregate_id`` or ``None``.

        ESS-INV-03: callers MUST rebuild by folding events from ``snap.version``
        onward; the snapshot is a cache, never the source of truth.
        """
        key = _check_aggregate_id(aggregate_id)
        with self._lock:
            return self._snapshots.get(key)

    # ----- introspection / observability helpers ----------------------------
    def current_version(self, aggregate_id: str) -> int:
        """Return the tail version for ``aggregate_id`` (0 if unknown)."""
        key = _check_aggregate_id(aggregate_id)
        with self._lock:
            return len(self._events.get(key, []))

    @property
    def aggregate_count(self) -> int:
        with self._lock:
            return len(self._events)

    def event_snapshot(self, aggregate_id: str) -> tuple[object, ...]:
        """Deep-copied tuple of stored events; for testing / observability."""
        key = _check_aggregate_id(aggregate_id)
        with self._lock:
            return tuple(copy.deepcopy(e) for e in self._events.get(key, ()))


# ---------------------------------------------------------------------------
# Extension point: fold / serializer registry
# ---------------------------------------------------------------------------
# A fold function maps (prior_state, event) -> new_state. Returning the same
# type every time keeps replays deterministic (ESS-INV-04).
FoldFn = Callable[[Any, Any], Any]
# A serializer maps (event) -> payload-bytes (or back). Storage backends plug
# through the adapter below without altering concurrency or replay semantics.
SerializerFn = Callable[[Any], Any]


class AggregateTypeRegistry:
    """Registry that associates an aggregate type with its fold + serializer.

    Downstream tools extend ``EventSourcedStore`` by registering a new
    aggregate type here; the registry is the stable extension contract cited
    in the catalog. Registration is write-once per type name: silent
    re-registration would mean two teams fold the same log differently, which
    breaks the replay determinism invariant (ESS-INV-04).
    """

    def __init__(self) -> None:
        self._folds: dict[str, FoldFn] = {}
        self._serializers: dict[str, SerializerFn] = {}
        self._lock = threading.Lock()

    def register(
        self,
        type_name: str,
        fold: FoldFn,
        serializer: SerializerFn,
    ) -> None:
        if not isinstance(type_name, str) or not type_name:
            raise EventSourcedStoreInvariantError(
                "ESS-INV-04: aggregate type_name MUST be a non-empty string."
            )
        if not callable(fold) or not callable(serializer):
            raise EventSourcedStoreInvariantError(
                "ESS-INV-04: fold and serializer MUST both be callable."
            )
        with self._lock:
            if type_name in self._folds:
                raise EventSourcedStoreInvariantError(
                    f"ESS-INV-04: aggregate type {type_name!r} is already "
                    f"registered; silent re-registration would break replay "
                    f"determinism."
                )
            self._folds[type_name] = fold
            self._serializers[type_name] = serializer

    def fold_for(self, type_name: str) -> FoldFn:
        with self._lock:
            try:
                return self._folds[type_name]
            except KeyError as exc:
                raise EventSourcedStoreInvariantError(
                    f"ESS-INV-04: aggregate type {type_name!r} is not "
                    f"registered; register its fold before replay."
                ) from exc

    def serializer_for(self, type_name: str) -> SerializerFn:
        with self._lock:
            try:
                return self._serializers[type_name]
            except KeyError as exc:
                raise EventSourcedStoreInvariantError(
                    f"ESS-INV-04: aggregate type {type_name!r} is not "
                    f"registered; register its serializer before replay."
                ) from exc

    def registered_types(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._folds))


# ---------------------------------------------------------------------------
# Replay helpers — deterministic fold over the log (ESS-INV-04)
# ---------------------------------------------------------------------------
def replay(
    store: InMemoryEventSourcedStore,
    aggregate_id: str,
    fold: FoldFn,
    initial_state: Any = None,
) -> tuple[Any, int]:
    """Fold every event of ``aggregate_id`` from zero with ``fold``.

    Returns ``(state, version)`` where ``version`` is the number of events
    folded. This function NEVER consults snapshots — it is the audit-grade
    replay that proves ``ESS-INV-03``: any snapshot must agree with the state
    produced here when folded to the same version.
    """
    events = list(store.load(aggregate_id))
    state: object = initial_state
    for event in events:
        state = fold(state, event)
    return state, len(events)


def replay_from_snapshot(
    store: InMemoryEventSourcedStore,
    aggregate_id: str,
    fold: FoldFn,
    initial_state: Any = None,
) -> tuple[Any, int]:
    """Fold from the latest snapshot forward when available, else from zero.

    Returns ``(state, version)``. The result MUST equal the result of
    :func:`replay` applied to the same inputs (ESS-INV-03).
    """
    snap = store.latest_snapshot(aggregate_id)
    if snap is None:
        return replay(store, aggregate_id, fold, initial_state)
    # Use `load_from` so only the tail (events strictly after the snapshot's
    # version) is materialised and deep-copied. For large aggregates this
    # turns the snapshot optimisation from "skip the fold" into "skip the
    # I/O AND the fold".
    tail_events: Iterator[object] = iter(store.load_from(aggregate_id, snap.version))
    state: object = snap.state  # deep-copied on egress from the snapshot
    folded = snap.version
    for event in tail_events:
        state = fold(state, event)
        folded += 1
    return state, folded


__all__ = [
    "AggregateTypeRegistry",
    "ConcurrencyError",
    "EventSourcedStore",
    "EventSourcedStoreInvariantError",
    "FoldFn",
    "InMemoryEventSourcedStore",
    "SerializerFn",
    "SnapshotRecord",
    "replay",
    "replay_from_snapshot",
]
