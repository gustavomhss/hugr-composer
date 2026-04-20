"""Aggregate primitive — Evans/Vernon DDD transactional-consistency boundary.

Implements the catalog Protocol for `data.Aggregate` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- AGG-INV-01: only the aggregate root MUST be referenced from outside the
  aggregate; external references to internal children are FORBIDDEN.
- AGG-INV-02: a single transaction MUST modify at most one aggregate
  instance; cross-aggregate changes SHALL be coordinated via domain events.
- AGG-INV-03: all invariants defined by the root MUST hold at the end of
  every public method; intermediate illegal states CANNOT be exposed.
- AGG-INV-04: the aggregate version NEVER decreases and MUST increment on
  every state-changing operation for optimistic concurrency.
- AGG-INV-05: external collaborators SHALL reference other aggregates by
  identifier only, NEVER by object reference.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Final, Generic, Protocol, TypeVar, runtime_checkable

# ---------------------------------------------------------------------------
# Type variables (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
ID = TypeVar("ID")
# Covariant variant used for the Protocol's read-only `id` property — mypy
# requires covariance for Protocol type parameters that appear only in
# covariant positions (return types).
ID_co = TypeVar("ID_co", covariant=True)


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class Aggregate(Protocol, Generic[ID_co]):
    @property
    def id(self) -> ID_co: ...
    @property
    def version(self) -> int: ...
    def pull_events(self) -> Iterable[object]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker + concurrency error
# ---------------------------------------------------------------------------
class AggregateInvariantError(RuntimeError):
    """Raised when an Aggregate invariant is violated at runtime."""


class OptimisticConcurrencyError(RuntimeError):
    """Raised when a stale version is detected during save (AGG-INV-04)."""


# ---------------------------------------------------------------------------
# Reference root implementation
# ---------------------------------------------------------------------------
class AggregateRoot(Generic[ID]):
    """Reference Aggregate root enforcing the five catalog invariants.

    Subclasses add domain-specific commands that call ``_mutate`` to apply a
    state change plus emit a domain event. ``_mutate`` increments the version
    and runs the subclass-declared invariant checker so illegal intermediate
    states CANNOT be exposed (AGG-INV-03).
    """

    # Subclasses MAY override to install stronger invariant checks.
    def _check_invariants(self) -> None:
        """AGG-INV-03 hook — raise AggregateInvariantError if state is illegal."""

    def __init__(self, aggregate_id: ID, *, version: int = 0) -> None:
        if version < 0:
            raise AggregateInvariantError(
                "AGG-INV-04: version NEVER decreases; initial version MUST be >= 0."
            )
        self._id: ID = aggregate_id
        self._version: int = version
        self._pending_events: list[object] = []
        self._lock = threading.RLock()
        # Guard: run invariants once so constructors expose only legal states.
        self._check_invariants()

    # ----- catalog Protocol surface -----------------------------------------
    @property
    def id(self) -> ID:
        return self._id

    @property
    def version(self) -> int:
        return self._version

    def pull_events(self) -> Iterable[object]:
        """Drain pending domain events. Returns a tuple snapshot, clears buffer."""
        with self._lock:
            events = tuple(self._pending_events)
            self._pending_events.clear()
            return events

    # ----- mutation helper (AGG-INV-03 + AGG-INV-04) ------------------------
    def _mutate(
        self,
        apply_change: Callable[[], None],
        event: object | None = None,
    ) -> None:
        """Apply a state change atomically, bump the version, check invariants.

        If ``apply_change`` raises or ``_check_invariants`` rejects the new
        state, the prior snapshot is restored so the aggregate NEVER exposes
        an illegal intermediate state (AGG-INV-03).
        """
        with self._lock:
            prior_version = self._version
            prior_events = list(self._pending_events)
            snapshot = self._snapshot()
            try:
                apply_change()
                self._version = prior_version + 1
                if event is not None:
                    self._pending_events.append(event)
                self._check_invariants()
            except BaseException:
                # Restore prior state — no partial mutations leak out.
                self._restore(snapshot)
                self._version = prior_version
                self._pending_events = prior_events
                raise

    # ----- snapshot hooks (subclasses override to support rollback) ---------
    def _snapshot(self) -> dict[str, object]:
        """Return a shallow copy of mutable state for rollback on failure.

        Subclasses MUST override to include their own fields. The default
        captures no domain state (version + events are handled by ``_mutate``).
        """
        return {}

    def _restore(self, snapshot: dict[str, object]) -> None:
        """Restore state captured by ``_snapshot``. Default is a no-op."""

    # ----- introspection ----------------------------------------------------
    @property
    def pending_event_count(self) -> int:
        with self._lock:
            return len(self._pending_events)


# ---------------------------------------------------------------------------
# Reference repository enforcing AGG-INV-02 + AGG-INV-04 at save time
# ---------------------------------------------------------------------------
class InMemoryAggregateRepository(Generic[ID]):
    """Minimal repository enforcing optimistic concurrency + single-aggregate save.

    AGG-INV-02: ``save`` accepts exactly one aggregate per call; multi-aggregate
    changes SHALL go through domain events rather than a joint save.
    AGG-INV-04: the stored version is compared with the incoming version; a
    stale write raises :class:`OptimisticConcurrencyError`.
    """

    def __init__(self) -> None:
        self._by_id: dict[object, tuple[AggregateRoot[ID], int]] = {}
        self._lock = threading.Lock()

    def save(self, aggregate: AggregateRoot[ID]) -> list[object]:
        with self._lock:
            stored = self._by_id.get(aggregate.id)
            if stored is not None:
                _, stored_version = stored
                # AGG-INV-04: refuse stale writes (incoming version MUST be greater).
                if aggregate.version <= stored_version:
                    raise OptimisticConcurrencyError(
                        f"AGG-INV-04: stale save — incoming version {aggregate.version} "
                        f"is not greater than stored version {stored_version}."
                    )
            self._by_id[aggregate.id] = (aggregate, aggregate.version)
        # Drain events AFTER the save succeeded so publishers only see committed state.
        return list(aggregate.pull_events())

    def get(self, aggregate_id: ID) -> AggregateRoot[ID]:
        with self._lock:
            stored = self._by_id.get(aggregate_id)
        if stored is None:
            raise KeyError(f"aggregate not found: {aggregate_id!r}")
        aggr, _ = stored
        return aggr

    def exists(self, aggregate_id: ID) -> bool:
        with self._lock:
            return aggregate_id in self._by_id


# ---------------------------------------------------------------------------
# Reference command / event plumbing (AGG-INV-05 demonstration)
# ---------------------------------------------------------------------------
class ForbiddenReferenceError(AggregateInvariantError):
    """AGG-INV-05: external collaborator referenced another aggregate by object."""


def require_identifier_reference(value: object) -> None:
    """Reject holding another AggregateRoot by reference (AGG-INV-05)."""
    if isinstance(value, AggregateRoot):
        raise ForbiddenReferenceError(
            "AGG-INV-05: cross-aggregate references MUST use identifiers, "
            "NEVER AggregateRoot object references."
        )


# ---------------------------------------------------------------------------
# Reference domain aggregate used by tests / docs
# ---------------------------------------------------------------------------
class _OrderLine:
    """Internal child entity of the OrderAggregate — never exposed externally.

    AGG-INV-01 forbids references to this class from outside OrderAggregate;
    callers MUST go through the root.
    """

    __slots__ = ("qty", "sku")

    def __init__(self, sku: str, qty: int) -> None:
        self.sku = sku
        self.qty = qty


class OrderPlaced:
    __slots__ = ("order_id",)

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id


class LineAdded:
    __slots__ = ("order_id", "qty", "sku")

    def __init__(self, order_id: str, sku: str, qty: int) -> None:
        self.order_id = order_id
        self.sku = sku
        self.qty = qty


class OrderAggregate(AggregateRoot[str]):
    """Concrete reference aggregate — an Order with private OrderLines."""

    MAX_LINES: Final[int] = 100

    def __init__(self, order_id: str, customer_id: str) -> None:
        # AGG-INV-05: customer_id is a string identifier, not a customer object.
        require_identifier_reference(customer_id)
        self._customer_id = customer_id
        self._lines: list[_OrderLine] = []
        super().__init__(order_id, version=0)
        # Emit a creation event as part of the initial version bump.
        self._mutate(lambda: None, event=OrderPlaced(order_id))

    # ----- snapshot rollback support ----------------------------------------
    def _snapshot(self) -> dict[str, object]:
        return {"lines": [(line.sku, line.qty) for line in self._lines]}

    def _restore(self, snapshot: dict[str, object]) -> None:
        raw = snapshot.get("lines", [])
        if not isinstance(raw, list):
            raise AggregateInvariantError(
                "AGG-INV-03: malformed snapshot — `lines` must be a list."
            )
        self._lines = [_OrderLine(sku, qty) for sku, qty in raw]

    # ----- invariants (AGG-INV-03) ------------------------------------------
    def _check_invariants(self) -> None:
        if len(self._lines) > self.MAX_LINES:
            raise AggregateInvariantError(
                f"AGG-INV-03: order exceeds MAX_LINES={self.MAX_LINES}; refusing illegal state."
            )
        for line in self._lines:
            if line.qty <= 0:
                raise AggregateInvariantError(
                    "AGG-INV-03: order line quantity MUST be positive."
                )

    # ----- commands ---------------------------------------------------------
    def add_line(self, sku: str, qty: int) -> None:
        def apply() -> None:
            self._lines.append(_OrderLine(sku, qty))

        self._mutate(apply, event=LineAdded(self.id, sku, qty))

    # ----- read surface (AGG-INV-01: only aggregated copies, not children) --
    @property
    def line_count(self) -> int:
        return len(self._lines)

    def line_summary(self) -> tuple[tuple[str, int], ...]:
        """Return an immutable projection — NEVER the internal _OrderLine objects."""
        return tuple((line.sku, line.qty) for line in self._lines)


__all__ = [
    "ID",
    "Aggregate",
    "AggregateInvariantError",
    "AggregateRoot",
    "ForbiddenReferenceError",
    "InMemoryAggregateRepository",
    "LineAdded",
    "OptimisticConcurrencyError",
    "OrderAggregate",
    "OrderPlaced",
    "require_identifier_reference",
]
