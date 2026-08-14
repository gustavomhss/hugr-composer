"""TransactionalOutbox primitive — Richardson Microservices Patterns dual-write guard.

Implements the catalog Protocol for `events.TransactionalOutbox` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- TXN-INV-01: enqueue MUST write the outbox row inside the same database
  transaction as the originating state change; cross-transaction writes are
  FORBIDDEN. Messages enqueued outside an active transaction SHALL raise.
- TXN-INV-02: a message MUST NOT be marked published until the broker has
  acknowledged it. mark_published on an unacked or missing id is FORBIDDEN.
- TXN-INV-03: the relay SHALL deliver at-least-once; consumers MUST be
  idempotent. Re-publication of already-failed messages is ALWAYS allowed.
- TXN-INV-04: ordering per partition key ALWAYS follows transaction commit
  order; reordering across commits is FORBIDDEN — pending() yields messages
  in monotonically increasing sequence per key.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Final, Literal, Protocol, Self, runtime_checkable

# ---------------------------------------------------------------------------
# Message status constants
# ---------------------------------------------------------------------------
_STATUS_PENDING: Final[str] = "pending"
_STATUS_PUBLISHED: Final[str] = "published"
_STATUS_FAILED: Final[str] = "failed"

_VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {_STATUS_PENDING, _STATUS_PUBLISHED, _STATUS_FAILED}
)


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class TransactionalOutbox(Protocol):
    def enqueue(self, destination: str, payload: Any, key: str) -> None: ...
    def pending(self, limit: int) -> Iterable[dict[str, object]]: ...
    def mark_published(self, message_id: str) -> None: ...
    def mark_failed(self, message_id: str, reason: str) -> None: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class TransactionalOutboxInvariantError(RuntimeError):
    """Raised when a TransactionalOutbox invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Message record
# ---------------------------------------------------------------------------
@dataclass
class OutboxMessage:
    """Outbox row. Snapshot-friendly — pending() returns copies as dicts."""

    message_id: str
    destination: str
    payload: object
    key: str
    sequence: int
    status: str = _STATUS_PENDING
    published_at: float | None = None
    failed_reason: str | None = None
    attempts: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "destination": self.destination,
            "payload": self.payload,
            "key": self.key,
            "sequence": self.sequence,
            "status": self.status,
            "published_at": self.published_at,
            "failed_reason": self.failed_reason,
            "attempts": self.attempts,
        }


# ---------------------------------------------------------------------------
# Transaction handle (models the shared DB transaction — TXN-INV-01)
# ---------------------------------------------------------------------------
@dataclass
class OutboxTransaction:
    """Models the DB transaction that brackets state+outbox writes.

    A single commit flushes BOTH the business aggregate rows (via on_commit
    hooks) AND the outbox rows atomically. If the transaction is rolled back,
    EVERY staged outbox row is discarded alongside the business mutations.
    """

    active: bool = True
    staged: list[OutboxMessage] = field(default_factory=list)
    committed: bool = False
    rolled_back: bool = False


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryTransactionalOutbox:
    """In-memory TransactionalOutbox that guarantees atomicity with business state.

    Design:

    * `begin()` opens a transaction — context-manager semantics ensure the
      transaction ALWAYS terminates (commit or rollback) per TXN-INV-01.
    * `enqueue(...)` inside the transaction STAGES an outbox row. The row is
      not visible to `pending()` until `commit()` succeeds.
    * `commit()` flushes business state via the registered `state_flush_fn`
      and THEN moves staged outbox rows into the durable store. Either both
      succeed or both are discarded (atomicity with business data).
    * Broker publication is out-of-band: the relay reads `pending()`,
      publishes each row, and calls `mark_published` ONLY after the broker
      acks (TXN-INV-02).
    * `pending()` yields rows in monotonically increasing `(key, sequence)`
      order — per-partition FIFO (TXN-INV-04).
    """

    def __init__(
        self,
        state_flush_fn: Callable[[OutboxTransaction], None] | None = None,
        *,
        broker_publish_fn: Callable[[OutboxMessage], bool] | None = None,
    ) -> None:
        self._state_flush_fn = state_flush_fn or (lambda _t: None)
        self._broker_publish_fn = broker_publish_fn
        self._store: dict[str, OutboxMessage] = {}
        self._sequence: int = 0
        self._current_txn: OutboxTransaction | None = None
        self._lock = threading.RLock()

    # ----- transaction lifecycle --------------------------------------------
    def begin(self) -> _OutboxTransactionScope:
        """Open a new DB transaction scope. Context-manager driven."""
        with self._lock:
            if self._current_txn is not None and self._current_txn.active:
                raise TransactionalOutboxInvariantError(
                    "TXN-INV-01: a transaction is already active; nested "
                    "transactions on the same outbox are FORBIDDEN — commit "
                    "or rollback the outer scope first."
                )
            txn = OutboxTransaction()
            self._current_txn = txn
        return _OutboxTransactionScope(self, txn)

    # ----- Protocol surface --------------------------------------------------
    def enqueue(self, destination: str, payload: Any, key: str) -> None:
        """Stage an outbox row inside the active transaction.

        TXN-INV-01: cross-transaction writes are FORBIDDEN. Calling enqueue
        without an active transaction raises TransactionalOutboxInvariantError.
        """
        if not destination:
            raise TransactionalOutboxInvariantError(
                "TXN-INV-01: destination MUST be a non-empty topic/queue name."
            )
        if not key:
            raise TransactionalOutboxInvariantError(
                "TXN-INV-04: key MUST be a non-empty partition key; ordering "
                "per-key is guaranteed only for keyed messages."
            )
        with self._lock:
            txn = self._current_txn
            if txn is None or not txn.active:
                raise TransactionalOutboxInvariantError(
                    "TXN-INV-01: enqueue called outside an active transaction; "
                    "cross-transaction writes to the outbox are FORBIDDEN."
                )
            self._sequence += 1
            msg = OutboxMessage(
                message_id=str(uuid.uuid4()),
                destination=destination,
                payload=payload,
                key=key,
                sequence=self._sequence,
            )
            txn.staged.append(msg)

    def pending(self, limit: int) -> Iterable[dict[str, object]]:
        """Return up to `limit` pending messages in per-key commit order.

        TXN-INV-04: ordering per partition key follows transaction commit
        order; the iterator yields monotonically increasing `sequence` per
        key.
        """
        if limit < 0:
            raise TransactionalOutboxInvariantError("TXN-INV-04: limit MUST be non-negative.")
        with self._lock:
            rows = [m for m in self._store.values() if m.status == _STATUS_PENDING]
        rows.sort(key=lambda m: (m.key, m.sequence))
        return [m.to_dict() for m in rows[:limit]]

    def mark_published(self, message_id: str) -> None:
        """Mark a message as broker-acknowledged.

        TXN-INV-02: callers MUST have received a broker ack before calling;
        the in-memory implementation verifies the message exists and is in
        an ackable state (pending or failed — failed messages may be retried
        and then succeed).
        """
        import time

        with self._lock:
            msg = self._store.get(message_id)
            if msg is None:
                raise TransactionalOutboxInvariantError(
                    f"TXN-INV-02: mark_published on unknown message_id={message_id!r}; "
                    "only messages that were enqueued+committed can be marked published."
                )
            if msg.status == _STATUS_PUBLISHED:
                # Idempotent: re-acking the same message is a no-op. This makes
                # the relay safe under at-least-once relay crashes (TXN-INV-03).
                return
            msg.status = _STATUS_PUBLISHED
            msg.published_at = time.time()
            msg.failed_reason = None
            msg.attempts += 1

    def mark_failed(self, message_id: str, reason: str) -> None:
        """Mark a message as failed; it remains eligible for retry.

        TXN-INV-03: the relay retries failed messages until the broker acks.
        Consumers therefore see at-least-once delivery and MUST be idempotent.
        """
        if not reason:
            raise TransactionalOutboxInvariantError(
                "TXN-INV-03: reason MUST be a non-empty diagnostic string."
            )
        with self._lock:
            msg = self._store.get(message_id)
            if msg is None:
                raise TransactionalOutboxInvariantError(
                    f"TXN-INV-03: mark_failed on unknown message_id={message_id!r}."
                )
            if msg.status == _STATUS_PUBLISHED:
                raise TransactionalOutboxInvariantError(
                    "TXN-INV-02: cannot fail an already-published message; broker ack is terminal."
                )
            msg.status = _STATUS_FAILED
            msg.failed_reason = reason
            msg.attempts += 1

    # ----- relay helper (TXN-INV-03) ----------------------------------------
    def relay_once(self, limit: int = 100) -> list[str]:
        """Drive one relay pass: publish pending rows via broker_publish_fn.

        Idempotent: consumers SHOULD dedupe by message_id because the relay
        may retry on crash. Returns the list of published message_ids.
        """
        if self._broker_publish_fn is None:
            raise TransactionalOutboxInvariantError(
                "TXN-INV-03: relay_once requires a broker_publish_fn — pass one "
                "at construction time to enable the relay."
            )
        published: list[str] = []
        with self._lock:
            candidates = [
                m for m in self._store.values() if m.status in (_STATUS_PENDING, _STATUS_FAILED)
            ]
        # Sort by (key, sequence) so per-partition order is preserved.
        candidates.sort(key=lambda m: (m.key, m.sequence))
        for m in candidates[:limit]:
            try:
                acked = self._broker_publish_fn(m)
            except BaseException as exc:
                self.mark_failed(m.message_id, f"publish_raised:{exc!r}"[:200])
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                    raise
                continue
            if acked:
                self.mark_published(m.message_id)
                published.append(m.message_id)
            else:
                self.mark_failed(m.message_id, "broker_nack")
        return published

    # ----- introspection -----------------------------------------------------
    @property
    def store_snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(m.to_dict() for m in self._store.values())

    @property
    def current_transaction(self) -> OutboxTransaction | None:
        return self._current_txn

    # ----- transaction finalization (called by the scope context manager) ---
    def finalize_commit(self, txn: OutboxTransaction) -> None:
        """Flush business state + outbox rows atomically.

        TXN-INV-01: state flush and outbox insert happen in the same DB
        transaction. If state flush raises, the staged outbox rows are
        DISCARDED.
        """
        with self._lock:
            if not txn.active:
                raise TransactionalOutboxInvariantError(
                    "TXN-INV-01: transaction is not active; commit is FORBIDDEN."
                )
            try:
                self._state_flush_fn(txn)
            except BaseException:
                # Business state flush failed — the whole transaction aborts.
                self.finalize_rollback(txn)
                raise
            # Commit the outbox rows atomically with the state flush.
            for msg in txn.staged:
                self._store[msg.message_id] = msg
            txn.committed = True
            txn.active = False
            if self._current_txn is txn:
                self._current_txn = None

    def finalize_rollback(self, txn: OutboxTransaction) -> None:
        with self._lock:
            txn.staged.clear()
            txn.rolled_back = True
            txn.active = False
            if self._current_txn is txn:
                self._current_txn = None


# ---------------------------------------------------------------------------
# Transaction scope (context manager enforcing lifecycle)
# ---------------------------------------------------------------------------
class _OutboxTransactionScope:
    """Context-manager wrapper that enforces commit-or-rollback on exit."""

    def __init__(
        self,
        owner: InMemoryTransactionalOutbox,
        txn: OutboxTransaction,
    ) -> None:
        self._owner = owner
        self._txn = txn

    @property
    def txn(self) -> OutboxTransaction:
        return self._txn

    def commit(self) -> None:
        self._owner.finalize_commit(self._txn)

    def rollback(self) -> None:
        self._owner.finalize_rollback(self._txn)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if exc_type is not None:
            if self._txn.active:
                self._owner.finalize_rollback(self._txn)
            return False
        # Normal exit without explicit commit → conservative rollback so
        # partial transactions NEVER silently leak outbox rows.
        if self._txn.active:
            self._owner.finalize_rollback(self._txn)
        return False


# ---------------------------------------------------------------------------
# Iterator helper so `pending()` satisfies Iterable at static check time
# ---------------------------------------------------------------------------
def _iter_pending(rows: list[dict[str, object]]) -> Iterator[dict[str, object]]:
    yield from rows


__all__ = [
    "InMemoryTransactionalOutbox",
    "OutboxMessage",
    "OutboxTransaction",
    "TransactionalOutbox",
    "TransactionalOutboxInvariantError",
]
