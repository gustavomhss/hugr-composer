"""InboxDeduplicator primitive — Richardson/Kleppmann idempotent-consumer dedupe.

Implements the catalog Protocol for `events.InboxDeduplicator` and installs
runtime invariant checkers. The module performs zero I/O at import.

Companion to TransactionalOutbox: the outbox solves the PRODUCER dual-write
trap; the inbox solves the CONSUMER redelivery trap. Together they bracket a
side-effect with (dedupe-check + business-tx + dedupe-record) in a single
atomic transaction so at-least-once transport yields exactly-once effect.

Invariant IDs cited by this module:

- INBOX-INV-01: ``record`` MUST be written in the SAME transaction as the
  consumer's side-effect; post-effect writes are FORBIDDEN. Calls outside an
  active transaction SHALL raise InboxDeduplicatorInvariantError.
- INBOX-INV-02: ``seen(message_id, consumer)`` MUST be deterministic for the
  same pair; once ``record`` commits, every subsequent ``seen`` in every
  transaction NEVER returns False for that pair until the row is purged
  OUTSIDE its retention window.
- INBOX-INV-03: ``purge_older_than`` SHALL refuse to evict rows whose age is
  less than the configured minimum redelivery window; premature purging is
  NEVER allowed.
- INBOX-INV-04: a missing record ALWAYS means first delivery; the
  deduplicator NEVER silently reclassifies an unseen ``(message_id, consumer)``
  as a duplicate — ``seen`` returns True IFF a committed record exists.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Final, Literal, Protocol, Self, runtime_checkable

# ---------------------------------------------------------------------------
# Lifecycle states for the bracketing transaction
# ---------------------------------------------------------------------------
_TXN_NONE: Final[str] = "none"
_TXN_ACTIVE: Final[str] = "active"
_TXN_COMMITTED: Final[str] = "committed"
_TXN_ROLLED_BACK: Final[str] = "rolled_back"

_TERMINAL_TXN_STATES: Final[frozenset[str]] = frozenset(
    {_TXN_COMMITTED, _TXN_ROLLED_BACK},
)

# Default minimum redelivery window (INBOX-INV-03). Seven days comfortably
# covers the typical broker redelivery horizon (Kafka default retention,
# RabbitMQ DLX loops, SQS 14-day max visibility cycles).
_DEFAULT_MIN_RETENTION: Final[timedelta] = timedelta(days=7)


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class InboxDeduplicator(Protocol):
    def seen(self, message_id: str, consumer: str) -> bool: ...
    def record(self, message_id: str, consumer: str) -> None: ...
    def purge_older_than(self, iso_timestamp: str) -> int: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class InboxDeduplicatorInvariantError(RuntimeError):
    """Raised when an InboxDeduplicator invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Inbox record
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InboxRecord:
    """One committed dedupe row — immutable once recorded (INBOX-INV-02)."""

    message_id: str
    consumer: str
    recorded_at_iso: str

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "consumer": self.consumer,
            "recorded_at_iso": self.recorded_at_iso,
        }


# ---------------------------------------------------------------------------
# Transaction handle — models the DB transaction bracketing the side-effect
# ---------------------------------------------------------------------------
@dataclass
class InboxTransaction:
    """Models the DB transaction bracketing (seen → effect → record) — INBOX-INV-01.

    The business side-effect callback runs INSIDE this transaction. Staged
    dedupe records flush atomically alongside the side-effect on commit. If
    the side-effect raises, every staged record is discarded.
    """

    state: str = _TXN_ACTIVE
    staged: list[InboxRecord] = field(default_factory=list)
    effect_ran: bool = False
    effect_completed: bool = False


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryInboxDeduplicator:
    """In-memory InboxDeduplicator with atomic (seen / record / side-effect).

    Design
    ------
    * ``begin()`` opens a dedupe transaction scope (context manager). Only
      inside the scope can ``record`` stage a new row (INBOX-INV-01).
    * ``seen(message_id, consumer)`` reflects the durably-committed store +
      rows staged by the CURRENT transaction. Two consecutive ``record``
      attempts for the same pair in the same txn raise — the caller is
      expected to ``seen``-gate first (INBOX-INV-02).
    * ``record(message_id, consumer)`` stages the dedupe row. It flushes on
      commit, ATOMIC with the side-effect. If commit or side-effect raises,
      rollback discards the staged row and ``seen`` returns False again
      (INBOX-INV-01 + INBOX-INV-04).
    * ``purge_older_than(iso_timestamp)`` refuses to evict rows whose age is
      shorter than the configured retention window (INBOX-INV-03).
    * The ``handle`` helper wires the recommended (seen → effect → record)
      sequence in one call so consumers that use the helper CANNOT drop the
      invariant structure.

    Thread-safety
    -------------
    One outstanding transaction per inbox instance; an RLock guards the store
    and transaction registry. Multiple readers of ``seen`` on committed rows
    are serialized by the lock but never block each other meaningfully (the
    dict lookup is O(1)).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        min_retention: timedelta = _DEFAULT_MIN_RETENTION,
    ) -> None:
        if min_retention.total_seconds() <= 0:
            raise InboxDeduplicatorInvariantError(
                "INBOX-INV-03: min_retention MUST be a positive timedelta; "
                "a non-positive window defeats redelivery protection.",
            )
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._min_retention: timedelta = min_retention
        self._store: dict[tuple[str, str], InboxRecord] = {}
        self._lock = threading.RLock()
        self._current_txn: InboxTransaction | None = None

    # ----- Protocol surface -------------------------------------------------
    def seen(self, message_id: str, consumer: str) -> bool:
        """Return True iff a record exists for (message_id, consumer).

        INBOX-INV-04: a missing record ALWAYS means first delivery; this
        method NEVER synthesizes a True result for an un-recorded pair. The
        check considers both the durable store AND the current transaction's
        staged rows so a consumer that calls ``seen`` after ``record`` inside
        the same transaction sees the staged row (enables idempotent retries
        within one txn while preserving INBOX-INV-02).
        """
        self._validate_identity(message_id, consumer)
        key = (message_id, consumer)
        with self._lock:
            if key in self._store:
                return True
            txn = self._current_txn
            if txn is not None and txn.state == _TXN_ACTIVE:
                for rec in txn.staged:
                    if (rec.message_id, rec.consumer) == key:
                        return True
            return False

    def record(self, message_id: str, consumer: str) -> None:
        """Stage a dedupe row inside the active transaction.

        INBOX-INV-01: outside an active transaction, ``record`` is FORBIDDEN —
        records that are not bracketed by the business side-effect lose the
        atomicity guarantee that makes exactly-once-effect possible.
        INBOX-INV-02: recording the same pair twice is FORBIDDEN; the second
        call signals a caller bug (forgot the ``seen`` gate).
        """
        self._validate_identity(message_id, consumer)
        with self._lock:
            txn = self._current_txn
            if txn is None or txn.state != _TXN_ACTIVE:
                raise InboxDeduplicatorInvariantError(
                    "INBOX-INV-01: record called outside an active transaction; "
                    "records MUST flush ATOMIC with the consumer side-effect.",
                )
            key = (message_id, consumer)
            if key in self._store:
                raise InboxDeduplicatorInvariantError(
                    "INBOX-INV-02: record on an already-committed pair "
                    f"({message_id!r}, {consumer!r}); callers MUST call "
                    "`seen` first and skip the side-effect on True.",
                )
            for rec in txn.staged:
                if (rec.message_id, rec.consumer) == key:
                    raise InboxDeduplicatorInvariantError(
                        "INBOX-INV-02: record on a pair already staged in "
                        "this transaction; duplicate staging is FORBIDDEN.",
                    )
            txn.staged.append(
                InboxRecord(
                    message_id=message_id,
                    consumer=consumer,
                    recorded_at_iso=self._clock().isoformat(),
                ),
            )

    def purge_older_than(self, iso_timestamp: str) -> int:
        """Evict records recorded strictly before ``iso_timestamp``.

        INBOX-INV-03: the cutoff MUST NOT intrude on the minimum redelivery
        window. A cutoff whose distance from *now* is smaller than
        ``self._min_retention`` is rejected as premature.
        Returns the number of evicted rows.
        """
        cutoff = _parse_iso8601_utc(iso_timestamp)
        now = self._clock_utc()
        if now - cutoff < self._min_retention:
            raise InboxDeduplicatorInvariantError(
                "INBOX-INV-03: purge cutoff too close to now "
                f"({(now - cutoff).total_seconds():.3f}s < "
                f"{self._min_retention.total_seconds():.3f}s retention); "
                "premature purging is FORBIDDEN.",
            )
        evicted = 0
        with self._lock:
            victims: list[tuple[str, str]] = []
            for key, rec in self._store.items():
                recorded = _parse_iso8601_utc(rec.recorded_at_iso)
                if recorded < cutoff:
                    victims.append(key)
            for key in victims:
                del self._store[key]
                evicted += 1
        return evicted

    # ----- transaction lifecycle -------------------------------------------
    def begin(self) -> _InboxTransactionScope:
        """Open a dedupe transaction. Context-manager driven."""
        with self._lock:
            if self._current_txn is not None and self._current_txn.state == _TXN_ACTIVE:
                raise InboxDeduplicatorInvariantError(
                    "INBOX-INV-01: a transaction is already active; nested "
                    "transactions on the same inbox are FORBIDDEN — commit "
                    "or rollback the outer scope first.",
                )
            txn = InboxTransaction()
            self._current_txn = txn
        return _InboxTransactionScope(self, txn)

    @contextmanager
    def handle(
        self,
        message_id: str,
        consumer: str,
        effect: Callable[[], None],
    ) -> Iterator[bool]:
        """Bracket one message: dedupe gate + side-effect + record, all atomic.

        Yields True if the side-effect ran (first delivery), False if it was
        skipped because the pair was already recorded. The dedupe record is
        committed IFF the effect callable returned without raising — so
        INBOX-INV-01 (same-transaction write) and INBOX-INV-04 (missing means
        first delivery) are both preserved mechanically.
        """
        self._validate_identity(message_id, consumer)
        with self.begin() as scope:
            if self.seen(message_id, consumer):
                yield False
                scope.commit()
                return
            scope.txn.effect_ran = True
            effect()
            scope.txn.effect_completed = True
            self.record(message_id, consumer)
            yield True
            scope.commit()

    # ----- introspection ---------------------------------------------------
    @property
    def store_snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(r.to_dict() for r in self._store.values())

    @property
    def current_transaction(self) -> InboxTransaction | None:
        return self._current_txn

    @property
    def min_retention(self) -> timedelta:
        return self._min_retention

    # ----- finalization (driven by the scope context manager) --------------
    def finalize_commit(self, txn: InboxTransaction) -> None:
        with self._lock:
            if txn.state != _TXN_ACTIVE:
                raise InboxDeduplicatorInvariantError(
                    "INBOX-INV-01: transaction is not active; commit is FORBIDDEN.",
                )
            # Flush staged dedupe rows atomically with the side-effect that
            # already ran inside the scope. Commit order is deterministic
            # (append order) so replay produces the same store.
            for rec in txn.staged:
                key = (rec.message_id, rec.consumer)
                # Re-check under lock — this catches a concurrent commit that
                # sneaked the same pair in (another thread's inbox instance
                # would need a distributed coordinator; in-process we just
                # guard the one store).
                if key in self._store:
                    raise InboxDeduplicatorInvariantError(
                        "INBOX-INV-02: concurrent duplicate for pair "
                        f"({rec.message_id!r}, {rec.consumer!r}); commit aborted.",
                    )
                self._store[key] = rec
            txn.state = _TXN_COMMITTED
            if self._current_txn is txn:
                self._current_txn = None

    def finalize_rollback(self, txn: InboxTransaction) -> None:
        with self._lock:
            txn.staged.clear()
            txn.state = _TXN_ROLLED_BACK
            if self._current_txn is txn:
                self._current_txn = None

    # ----- guards ----------------------------------------------------------
    @staticmethod
    def _validate_identity(message_id: str, consumer: str) -> None:
        if not message_id:
            raise InboxDeduplicatorInvariantError(
                "INBOX-INV-04: message_id MUST be a non-empty identifier; "
                "empty ids cannot be deduped safely.",
            )
        if not consumer:
            raise InboxDeduplicatorInvariantError(
                "INBOX-INV-04: consumer MUST be a non-empty name; the same "
                "message may be processed by distinct consumers.",
            )

    def _clock_utc(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)


# ---------------------------------------------------------------------------
# Transaction scope — enforces commit-or-rollback on exit
# ---------------------------------------------------------------------------
class _InboxTransactionScope:
    """Context-manager wrapper that enforces commit-or-rollback lifecycle."""

    def __init__(
        self,
        owner: InMemoryInboxDeduplicator,
        txn: InboxTransaction,
    ) -> None:
        self._owner = owner
        self._txn = txn

    @property
    def txn(self) -> InboxTransaction:
        return self._txn

    def commit(self) -> None:
        self._owner.finalize_commit(self._txn)

    def rollback(self) -> None:
        if self._txn.state in _TERMINAL_TXN_STATES:
            return
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
            if self._txn.state == _TXN_ACTIVE:
                self._owner.finalize_rollback(self._txn)
            return False
        # Normal exit without explicit commit → conservative rollback so
        # partial transactions NEVER silently leak dedupe rows.
        if self._txn.state == _TXN_ACTIVE:
            self._owner.finalize_rollback(self._txn)
        return False


# ---------------------------------------------------------------------------
# ISO-8601 helpers — ALWAYS anchor to UTC (avoids DST / locale ambiguity)
# ---------------------------------------------------------------------------
def _parse_iso8601_utc(value: str) -> datetime:
    if not value:
        raise InboxDeduplicatorInvariantError(
            "INBOX-INV-03: iso_timestamp MUST be a non-empty ISO-8601 string.",
        )
    text = value.strip()
    # Normalise trailing 'Z' (RFC 3339 convention) which fromisoformat rejects
    # on Python versions < 3.11 — the project supports 3.12+ but we keep the
    # guard so future downgrades stay safe.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InboxDeduplicatorInvariantError(
            f"INBOX-INV-03: iso_timestamp not parseable as ISO-8601: {value!r}",
        ) from exc
    if dt.tzinfo is None:
        # Naive timestamps are ambiguous — require UTC or an explicit offset.
        raise InboxDeduplicatorInvariantError(
            "INBOX-INV-03: iso_timestamp MUST carry a timezone "
            "(append 'Z' or an offset like '+00:00').",
        )
    return dt.astimezone(UTC)


__all__ = [
    "InMemoryInboxDeduplicator",
    "InboxDeduplicator",
    "InboxDeduplicatorInvariantError",
    "InboxRecord",
    "InboxTransaction",
]
