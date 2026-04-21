"""Bulkhead primitive — Nygard stability-pattern concurrency partitioner.

Implements the catalog Protocol for ``resiliency.Bulkhead`` and installs
runtime invariant checkers. The module performs zero I/O at import; optional
SDKs are imported lazily inside function bodies. The reference implementation
is a ``semaphore`` kind adapter that bounds in-flight async calls per
partition with an isolated permit counter and a bounded acquisition wait.

Invariant IDs cited by this module:

- BH_INV_01: the number of in-flight calls per partition MUST NEVER exceed
  ``max_concurrent_calls``. A runtime checker asserts ``in_flight <= capacity``
  on every state mutation (acquire / release) and raises
  ``BulkheadInvariantError`` on drift.
- BH_INV_02: a caller that waits longer than ``max_wait_duration_ms`` for a
  permit SHALL receive ``BulkheadFull`` and NEVER be admitted. The acquisition
  code path uses ``asyncio.wait_for`` with the declared timeout; the wrapped
  callable is not invoked on timeout.
- BH_INV_03: a rejection by Bulkhead MUST NOT be retried inside the same
  partition in the same request. A per-request rejection ledger
  (``RequestRejectionLedger``) records the (request_id, partition) pair and
  rejects any subsequent ``submit`` on the same pair.
- BH_INV_04: permits CANNOT be shared across partitions; each partition holds
  an isolated counter. The ``PartitionRegistry`` keeps one
  ``InMemoryBulkhead`` per name; cross-partition lookup returns a distinct
  semaphore instance and the runtime checker guards against accidental reuse.
- BH_INV_05: the bulkhead SHALL emit a rejection metric labelled with the
  partition name on every rejection. An in-memory ``RejectionMeter`` records
  every rejection event; integrations forward it to the metrics bus.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Types mirroring the catalog api_signature verbatim
# ---------------------------------------------------------------------------
Kind = Literal["semaphore", "thread_pool"]
_VALID_KINDS: Final[frozenset[str]] = frozenset({"semaphore", "thread_pool"})


# ---------------------------------------------------------------------------
# Invariant / rejection error taxonomy
# ---------------------------------------------------------------------------
class BulkheadError(RuntimeError):
    """Base class for every error raised by the Bulkhead primitive."""


class BulkheadFull(BulkheadError):  # noqa: N818 — BH_INV_02: catalog prose names this exception `BulkheadFull` (not `BulkheadFullError`) to match Nygard / resilience4j taxonomy; renaming would diverge from the sealed consumption example.
    """Raised when a caller cannot acquire a permit within the wait deadline.

    Maps to BH_INV_02 (timeout rejection) and BH_INV_01 (capacity rejection) —
    the two admission-refusal paths share one exception type so callers treat
    partition saturation uniformly.
    """

    def __init__(self, partition: str, reason: str) -> None:
        super().__init__(f"BulkheadFull[{partition}]: {reason}")
        self.partition: str = partition
        self.reason: str = reason


class BulkheadInvariantError(BulkheadError):
    """Raised when a Bulkhead invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Protocol surface (matches the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class Bulkhead(Protocol):
    """Partitioned concurrency limiter — bounded slots + bounded wait."""

    name: str
    kind: Kind
    max_concurrent_calls: int
    max_wait_duration_ms: int

    async def submit(
        self,
        fn: Callable[..., Awaitable[T]],
        /,
        *args: object,
        **kwargs: object,
    ) -> T: ...

    def available_permits(self) -> int: ...


# ---------------------------------------------------------------------------
# Rejection observability (BH_INV_05)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RejectionEvent:
    """One observable rejection. Carries the partition label required by BH_INV_05."""

    partition: str
    reason: str
    monotonic_ns: int


class RejectionMeter:
    """Thread-safe accumulator of rejection events — mandatory per BH_INV_05.

    The integration layer wires ``events`` onto the metrics bus; a missing
    partition label there is a contract violation — the label is always present
    because ``RejectionEvent.partition`` is non-optional.
    """

    def __init__(self) -> None:
        self._events: list[RejectionEvent] = []
        self._by_partition: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def record(self, partition: str, reason: str) -> RejectionEvent:
        if not isinstance(partition, str) or partition == "":
            raise BulkheadInvariantError(
                "BH_INV_05: RejectionEvent.partition MUST be a non-empty str; "
                "an unlabelled rejection CANNOT be emitted."
            )
        ev = RejectionEvent(
            partition=partition,
            reason=reason,
            monotonic_ns=time.monotonic_ns(),
        )
        with self._lock:
            self._events.append(ev)
            self._by_partition[partition] += 1
        return ev

    @property
    def events(self) -> tuple[RejectionEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def count_for(self, partition: str) -> int:
        with self._lock:
            return self._by_partition.get(partition, 0)


# ---------------------------------------------------------------------------
# Per-request rejection ledger (BH_INV_03)
# ---------------------------------------------------------------------------
class RequestRejectionLedger:
    """Tracks (request_id, partition) pairs to forbid intra-request retries.

    A rejection recorded for (r, p) CANNOT be retried on the same partition
    inside the same request; the ledger raises ``BulkheadInvariantError`` on
    any attempt. The ledger is cleared explicitly at the end of a request via
    ``clear_request``.
    """

    def __init__(self) -> None:
        self._rejected: dict[str, set[str]] = defaultdict(set)
        self._lock = threading.Lock()

    def has_rejection(self, request_id: str, partition: str) -> bool:
        with self._lock:
            return partition in self._rejected.get(request_id, set())

    def record(self, request_id: str, partition: str) -> None:
        if not isinstance(request_id, str) or request_id == "":
            raise BulkheadInvariantError(
                "BH_INV_03: request_id MUST be a non-empty str to anchor "
                "rejection ledger entries."
            )
        with self._lock:
            self._rejected[request_id].add(partition)

    def guard_retry(self, request_id: str, partition: str) -> None:
        """Raise if (request_id, partition) has already been rejected."""
        with self._lock:
            if partition in self._rejected.get(request_id, set()):
                raise BulkheadInvariantError(
                    f"BH_INV_03: partition {partition!r} already rejected "
                    f"request {request_id!r}; intra-request retry is FORBIDDEN."
                )

    def clear_request(self, request_id: str) -> None:
        with self._lock:
            self._rejected.pop(request_id, None)


# ---------------------------------------------------------------------------
# Reference semaphore bulkhead (the sealed in-memory adapter)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _PermitState:
    """Internal bookkeeping — NEVER exposed to adopters.

    ``in_flight`` MUST satisfy ``0 <= in_flight <= capacity`` at every
    observable moment (BH_INV_01). The state is serialised by the asyncio
    semaphore + a threading lock for the counter snapshot.
    """

    capacity: int
    in_flight: int = 0
    total_admitted: int = 0
    total_rejected: int = 0
    max_observed_in_flight: int = 0
    waiters_peak: int = 0


class InMemoryBulkhead:
    """Async semaphore bulkhead — the reference implementation.

    Carries its own ``RejectionMeter`` (mandatory per BH_INV_05) and an
    optional shared ``RequestRejectionLedger`` (BH_INV_03). A separate
    partition MUST hold a distinct instance — cross-partition permit sharing
    is FORBIDDEN by construction (BH_INV_04).
    """

    def __init__(
        self,
        name: str,
        *,
        max_concurrent_calls: int,
        max_wait_duration_ms: int,
        meter: RejectionMeter | None = None,
        ledger: RequestRejectionLedger | None = None,
    ) -> None:
        if not isinstance(name, str) or name == "":
            raise BulkheadInvariantError(
                "BH_INV_04: Bulkhead.name MUST be a non-empty str — partitions "
                "are looked up by name and an empty name breaks isolation."
            )
        if max_concurrent_calls < 1:
            raise BulkheadInvariantError(
                f"BH_INV_01: max_concurrent_calls MUST be >= 1, got "
                f"{max_concurrent_calls}; a zero-capacity bulkhead rejects "
                "every call silently."
            )
        if max_wait_duration_ms < 0:
            raise BulkheadInvariantError(
                f"BH_INV_02: max_wait_duration_ms MUST be >= 0, got "
                f"{max_wait_duration_ms}; a negative deadline is undefined."
            )
        self.name: str = name
        self.kind: Kind = "semaphore"
        self.max_concurrent_calls: int = max_concurrent_calls
        self.max_wait_duration_ms: int = max_wait_duration_ms
        self._state = _PermitState(capacity=max_concurrent_calls)
        self._state_lock = threading.Lock()
        self._sem = asyncio.Semaphore(max_concurrent_calls)
        self._meter: RejectionMeter = meter if meter is not None else RejectionMeter()
        self._ledger: RequestRejectionLedger | None = ledger

    # ---- introspection ----------------------------------------------------
    @property
    def meter(self) -> RejectionMeter:
        return self._meter

    @property
    def ledger(self) -> RequestRejectionLedger | None:
        return self._ledger

    def available_permits(self) -> int:
        # BH_INV_01: never report more than capacity.
        with self._state_lock:
            avail = self._state.capacity - self._state.in_flight
            if avail < 0 or avail > self._state.capacity:
                raise BulkheadInvariantError(
                    f"BH_INV_01: internal drift on {self.name!r}: avail={avail}, "
                    f"capacity={self._state.capacity}, in_flight={self._state.in_flight}."
                )
            return avail

    def in_flight(self) -> int:
        with self._state_lock:
            return self._state.in_flight

    def max_observed_in_flight(self) -> int:
        with self._state_lock:
            return self._state.max_observed_in_flight

    def total_admitted(self) -> int:
        with self._state_lock:
            return self._state.total_admitted

    def total_rejected(self) -> int:
        with self._state_lock:
            return self._state.total_rejected

    # ---- internal permit accounting ---------------------------------------
    def _acquire_slot(self) -> None:
        """Increment the slot counter under the state lock with a runtime check."""
        with self._state_lock:
            nxt = self._state.in_flight + 1
            if nxt > self._state.capacity:
                # BH_INV_01: this MUST never happen because the semaphore gates
                # admission, but we guard explicitly — drift is a crash, not a
                # log line.
                raise BulkheadInvariantError(
                    f"BH_INV_01: in_flight would exceed capacity on "
                    f"{self.name!r}: {nxt} > {self._state.capacity}."
                )
            self._state.in_flight = nxt
            self._state.total_admitted += 1
            self._state.max_observed_in_flight = max(
                self._state.max_observed_in_flight, nxt
            )

    def _release_slot(self) -> None:
        with self._state_lock:
            if self._state.in_flight <= 0:
                raise BulkheadInvariantError(
                    f"BH_INV_01: release without outstanding permit on "
                    f"{self.name!r}."
                )
            self._state.in_flight -= 1

    def _record_rejection(self, reason: str) -> None:
        with self._state_lock:
            self._state.total_rejected += 1
        # BH_INV_05: every rejection emits a partition-labelled metric.
        self._meter.record(self.name, reason)

    # ---- public acquire (BH_INV_01 / BH_INV_02 / BH_INV_03) ---------------
    @asynccontextmanager
    async def acquire(
        self, *, request_id: str | None = None
    ) -> AsyncIterator[None]:
        """Hold one permit for the duration of the ``async with`` block.

        ``acquire`` is the permit-accounting primitive; ``submit`` is sugar
        over it. Same three refusal paths:

        1. BH_INV_03 — the per-request ledger already recorded a rejection
           for this partition on this request; fail fast without queuing.
        2. BH_INV_02 — permit not available within
           ``max_wait_duration_ms``; record a partition-labelled metric and
           raise ``BulkheadFull``. The ``async with`` body is NEVER entered.
        3. BH_INV_01 — impossible under correct semaphore usage, but a drift
           is caught by the accounting assertions inside ``_acquire_slot``.

        Usage::

            async with bh.acquire():
                return await call_next(request)

        Or with request-scoped anti-retry::

            async with bh.acquire(request_id="req-123"):
                ...
        """
        if (
            self._ledger is not None
            and request_id is not None
            and request_id != ""
        ):
            # BH_INV_03: fail fast on intra-request retry.
            if self._ledger.has_rejection(request_id, self.name):
                self._record_rejection("retry_forbidden")
                raise BulkheadFull(
                    self.name,
                    f"request {request_id!r} was already rejected by this "
                    "partition; intra-request retry is FORBIDDEN.",
                )

        timeout_s: float = self.max_wait_duration_ms / 1000.0
        # Zero-wait path uses a microscopic deadline so wait_for rejects
        # immediately when no permit is free; non-zero path queues up to the
        # declared deadline.
        effective_timeout = timeout_s if timeout_s > 0.0 else 1e-9
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=effective_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            # BH_INV_02: wait exceeded → reject, record, DO NOT enter the body.
            self._record_rejection("wait_timeout")
            if (
                self._ledger is not None
                and request_id is not None
                and request_id != ""
            ):
                self._ledger.record(request_id, self.name)
            raise BulkheadFull(
                self.name,
                f"no permit available within {self.max_wait_duration_ms}ms "
                f"(capacity={self.max_concurrent_calls}).",
            ) from None

        # Permit acquired — account for it under the state lock.
        self._acquire_slot()
        try:
            yield
        finally:
            self._release_slot()
            self._sem.release()

    # ---- public submit — sugar over ``acquire`` ---------------------------
    async def submit(
        self,
        fn: Callable[..., Awaitable[T]],
        /,
        *args: object,
        **kwargs: object,
    ) -> T:
        """Acquire a permit, invoke ``fn``, release the permit.

        Thin sugar over ``acquire()`` so callers who only need "run this
        coroutine under the bulkhead" don't have to write the context
        manager. Behaviour is identical to ``acquire`` for all three refusal
        paths (BH_INV_01 / BH_INV_02 / BH_INV_03).
        """
        request_id = self._extract_request_id(kwargs)
        async with self.acquire(request_id=request_id):
            return await fn(*args, **kwargs)

    @staticmethod
    def _extract_request_id(kwargs: Mapping[str, object]) -> str | None:
        rid = kwargs.get("request_id")
        return rid if isinstance(rid, str) and rid else None


# ---------------------------------------------------------------------------
# Partition registry (BH_INV_04)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PartitionConfig:
    """Static declaration of one partition — used to seed a registry."""

    name: str
    max_concurrent_calls: int
    max_wait_duration_ms: int


class PartitionRegistry:
    """Maps a partition name to exactly one InMemoryBulkhead instance.

    BH_INV_04: registering the same name twice is FORBIDDEN; two partitions
    NEVER share a permit counter. A ``PartitionRouter`` hook can be attached
    to route a request to a partition name.
    """

    def __init__(
        self,
        meter: RejectionMeter | None = None,
        ledger: RequestRejectionLedger | None = None,
    ) -> None:
        self._partitions: dict[str, InMemoryBulkhead] = {}
        self._meter: RejectionMeter = meter if meter is not None else RejectionMeter()
        self._ledger: RequestRejectionLedger = (
            ledger if ledger is not None else RequestRejectionLedger()
        )
        self._router: Callable[[Mapping[str, object]], str] | None = None
        self._lock = threading.Lock()

    @property
    def meter(self) -> RejectionMeter:
        return self._meter

    @property
    def ledger(self) -> RequestRejectionLedger:
        return self._ledger

    def register(self, config: PartitionConfig) -> InMemoryBulkhead:
        with self._lock:
            if config.name in self._partitions:
                raise BulkheadInvariantError(
                    f"BH_INV_04: partition {config.name!r} is already "
                    "registered; distinct partitions MUST hold distinct "
                    "permit counters."
                )
            bh = InMemoryBulkhead(
                name=config.name,
                max_concurrent_calls=config.max_concurrent_calls,
                max_wait_duration_ms=config.max_wait_duration_ms,
                meter=self._meter,
                ledger=self._ledger,
            )
            self._partitions[config.name] = bh
            return bh

    def get(self, name: str) -> InMemoryBulkhead:
        with self._lock:
            if name not in self._partitions:
                raise BulkheadInvariantError(
                    f"BH_INV_04: partition {name!r} is not registered; "
                    "unknown partitions CANNOT borrow permits from known ones."
                )
            return self._partitions[name]

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._partitions.keys()))

    def set_router(
        self, router: Callable[[Mapping[str, object]], str]
    ) -> None:
        self._router = router

    def route(self, request: Mapping[str, object]) -> InMemoryBulkhead:
        if self._router is None:
            raise BulkheadInvariantError(
                "BH_INV_04: no PartitionRouter registered — routing a "
                "request without a hook would violate partition isolation."
            )
        name = self._router(request)
        return self.get(name)


# ---------------------------------------------------------------------------
# Simple helper dataclass used by tests / integration code.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BulkheadStats:
    """Snapshot of a partition's live counters — read-only."""

    name: str
    capacity: int
    in_flight: int
    available: int
    total_admitted: int
    total_rejected: int
    max_observed_in_flight: int
    rejection_labels: tuple[str, ...] = field(default_factory=tuple)


def snapshot(bulkhead: InMemoryBulkhead) -> BulkheadStats:
    """Return a BulkheadStats snapshot — useful for assertions in tests."""
    return BulkheadStats(
        name=bulkhead.name,
        capacity=bulkhead.max_concurrent_calls,
        in_flight=bulkhead.in_flight(),
        available=bulkhead.available_permits(),
        total_admitted=bulkhead.total_admitted(),
        total_rejected=bulkhead.total_rejected(),
        max_observed_in_flight=bulkhead.max_observed_in_flight(),
        rejection_labels=tuple(
            sorted({e.partition for e in bulkhead.meter.events})
        ),
    )


__all__ = [
    "Bulkhead",
    "BulkheadError",
    "BulkheadFull",
    "BulkheadInvariantError",
    "BulkheadStats",
    "InMemoryBulkhead",
    "Kind",
    "PartitionConfig",
    "PartitionRegistry",
    "RejectionEvent",
    "RejectionMeter",
    "RequestRejectionLedger",
    "snapshot",
]
