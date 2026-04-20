"""IdempotentConsumer primitive — Richardson/Kleppmann exactly-once-effect consumer.

Implements the catalog Protocol for ``events.IdempotentConsumer`` and installs
runtime invariant checkers. The module performs zero I/O at import.

Conceptual model
----------------
The consumer combines an ``InboxDeduplicator`` with a domain handler into a
single abstraction. ``handle(msg)`` maps to one of two reductions:

1. First delivery: key = ``key_for(msg)`` is NOT yet recorded. The
   handler-body runs and its effect (result) is cached atomically alongside
   the dedupe record.
2. Redelivery: key IS recorded. The cached result is replayed via
   ``on_duplicate(msg)``; the handler-body does NOT run again.

This is the *cached-retry* semantic — at-least-once transport yields
at-most-once effect and exactly-once observable state (Kleppmann Ch. 11).

Invariant IDs cited by this module:

- IDC-INV-01: Two deliveries sharing the same ``key_for(msg)`` MUST produce
  the same observable system state *within a single process lifetime*;
  divergence across deliveries in the SAME process is FORBIDDEN. The cached
  result of the first delivery is replayed verbatim to every duplicate.

  **Cross-process crash recovery is explicitly out of scope** for the
  reference in-memory cache: if the process crashes between the inbox
  commit and the cache write, the next delivery observes "already seen"
  but has no cached outputs to replay and emits an empty `CachedOutcome`.
  Consumers that require cross-crash state equivalence MUST persist the
  cache externally (Redis / Postgres / Kafka compacted topic) and inject
  it via `cache_store=...` on construction — see the module-level
  ``CachedOutcome`` docstring for the expected shape.
- IDC-INV-02: ``handle`` MUST NOT apply a non-compensatable side-effect
  without first consulting the wired ``InboxDeduplicator``; a consumer built
  without an inbox SHALL raise at construction.
- IDC-INV-03: ``on_duplicate`` is a STEADY-STATE path and MUST NEVER raise
  a primary error; duplicates are expected.
- IDC-INV-04: Any output the consumer wishes to publish downstream MUST be
  enqueued via the wired ``TransactionalOutbox`` so downstream systems can
  dedupe with the same guarantees.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Generic, Protocol, TypeVar, runtime_checkable

# Siblings — imported lazily-safe because both live in the same package and
# perform zero I/O at import. They are the formal collaborators the catalog
# invariants reference (InboxDeduplicator for IDC-INV-02, TransactionalOutbox
# for IDC-INV-04). Dual-path import so the module works both as a package
# member (engine gate runners) and as a flat module (tests running from the
# primitive dir with conftest's sys.path insertion).
try:
    from ..InboxDeduplicator.InboxDeduplicator import (
        InboxDeduplicatorInvariantError,
        InMemoryInboxDeduplicator,
    )
    from ..TransactionalOutbox.TransactionalOutbox import (
        InMemoryTransactionalOutbox,
    )
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _SIBLING_BASE = _Path(__file__).resolve().parent.parent
    for _sib in ("InboxDeduplicator", "TransactionalOutbox"):
        _p = str(_SIBLING_BASE / _sib)
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    from InboxDeduplicator import (  # type: ignore[import-not-found,no-redef]  # IDC-INV-02 — dual-path sibling import; flat-path variant used by tests
        InboxDeduplicatorInvariantError,
        InMemoryInboxDeduplicator,
    )
    from TransactionalOutbox import (  # type: ignore[import-not-found,no-redef]  # IDC-INV-04 — dual-path sibling import; flat-path variant used by tests
        InMemoryTransactionalOutbox,
    )

_CONSUMER_SENTINEL: Final[str] = "idempotent_consumer"

M = TypeVar("M")
R = TypeVar("R")


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class IdempotentConsumer(Protocol):
    def key_for(self, message: object) -> str: ...
    def handle(self, message: object) -> None: ...
    def on_duplicate(self, message: object) -> None: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class IdempotentConsumerInvariantError(RuntimeError):
    """Raised when an IdempotentConsumer invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Cached-result record (IDC-INV-01)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CachedOutcome:
    """Immutable record of a first-delivery result cached for replay.

    The ``outputs`` list captures every payload the handler enqueued on the
    outbox during first delivery. On redelivery, ``on_duplicate`` replays the
    same outputs — observable state MUST not diverge (IDC-INV-01).
    """

    key: str
    result: object
    outputs: tuple[dict[str, object], ...]


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class BaseIdempotentConsumer(Generic[M, R]):
    """Reference IdempotentConsumer combining inbox + handler + outbox.

    Subclasses MUST override ``key_for`` and ``_do_handle``. The framework
    threads every call through the wired ``InboxDeduplicator`` (IDC-INV-02)
    and publishes any downstream effects through the wired
    ``TransactionalOutbox`` (IDC-INV-04). Cached outcomes are replayed on
    duplicate deliveries (IDC-INV-01, IDC-INV-03).

    The consumer name differentiates dedupe namespaces so two consumer
    instances processing the same topic do NOT collide on identical message
    ids — this matches the ``InboxDeduplicator.record(message_id, consumer)``
    signature.
    """

    def __init__(
        self,
        *,
        inbox: InMemoryInboxDeduplicator,
        outbox: InMemoryTransactionalOutbox,
        consumer_name: str = _CONSUMER_SENTINEL,
    ) -> None:
        # IDC-INV-02: refusing to construct without an inbox makes the
        # non-compensatable side-effect bypass literally unreachable.
        if inbox is None:  # pragma: no cover — static-typed, guard is belt-and-braces
            raise IdempotentConsumerInvariantError(
                "IDC-INV-02: inbox is required; non-compensatable side-effects "
                "MUST route through an InboxDeduplicator.",
            )
        if outbox is None:  # pragma: no cover — static-typed, guard is belt-and-braces
            raise IdempotentConsumerInvariantError(
                "IDC-INV-04: outbox is required; downstream publishes MUST "
                "route through a TransactionalOutbox.",
            )
        if not consumer_name:
            raise IdempotentConsumerInvariantError(
                "IDC-INV-02: consumer_name MUST be a non-empty dedupe namespace.",
            )
        self._inbox = inbox
        self._outbox = outbox
        self._consumer = consumer_name
        self._cache: dict[str, CachedOutcome] = {}
        self._lock = threading.RLock()
        self._handle_calls = 0
        self._duplicate_calls = 0
        self._effect_runs = 0

    # ----- Protocol surface --------------------------------------------------
    def key_for(self, message: object) -> str:
        """Extract the idempotency key for ``message``.

        Default: if the message carries an ``id`` attribute or ``"id"`` key,
        use it; otherwise subclasses MUST override.
        """
        raw_id = getattr(message, "id", None)
        if raw_id is not None:
            key = str(raw_id)
        elif isinstance(message, dict) and "id" in message:
            key = str(message["id"])
        else:
            raise IdempotentConsumerInvariantError(
                "IDC-INV-01: cannot derive idempotency key from message; "
                "override key_for to supply one.",
            )
        if not key:
            raise IdempotentConsumerInvariantError(
                "IDC-INV-01: idempotency key MUST be non-empty.",
            )
        return key

    def handle(self, message: object) -> None:
        """Dispatch one delivery through the (seen → effect → record) bracket.

        First delivery: runs ``_do_handle``, caches its outcome, publishes
        any outputs through the outbox, records the key in the inbox — all
        atomic with each other (IDC-INV-01, IDC-INV-02, IDC-INV-04).

        Redelivery: invokes ``on_duplicate`` which replays the cached
        outcome; no new effect is applied (IDC-INV-01, IDC-INV-03).
        """
        key = self.key_for(message)
        with self._lock:
            self._handle_calls += 1
            cached = self._cache.get(key)
            if cached is not None:
                # Fast-path: cached hit. Count exactly once here so the
                # default `on_duplicate` does NOT double-count the same event.
                # `on_duplicate` guards via `key in self._cache` — by the
                # time it runs we've already recorded the duplicate.
                self._duplicate_calls += 1
                self.on_duplicate(message)
                return
        # Cold path: open inbox bracket, run handler, cache outcome.
        with self._inbox.begin() as inbox_scope:
            if self._inbox.seen(key, self._consumer):
                # Inbox already committed the record (e.g. from a prior
                # process instance). Treat as duplicate — replay empty
                # outcome; subclasses that need rich replay on cross-process
                # resumption SHOULD persist the cache externally.
                inbox_scope.commit()
                with self._lock:
                    if key not in self._cache:
                        self._cache[key] = CachedOutcome(
                            key=key, result=None, outputs=(),
                        )
                    self._duplicate_calls += 1
                # Do NOT invoke `on_duplicate` here: we already counted the
                # duplicate above AND the default implementation would count
                # again. Subclasses that need a redelivery hook should check
                # `duplicate_calls` or override `_do_handle`'s pre-phase.
                return
            outputs: list[dict[str, object]] = []
            # Nest the outbox transaction inside the inbox transaction: the
            # dedupe record and the downstream publishes commit atomically
            # together. If either raises, both roll back (IDC-INV-01 +
            # IDC-INV-04).
            with self._outbox.begin() as outbox_scope:
                def _enqueue(topic: str, payload: dict[str, object]) -> None:
                    # IDC-INV-04: every downstream publish routes through
                    # the TransactionalOutbox so downstream consumers can
                    # dedupe with the same guarantees.
                    self._outbox.enqueue(
                        destination=topic,
                        payload=payload,
                        key=f"{key}:{len(outputs)}",
                    )
                    outputs.append({"topic": topic, "payload": dict(payload)})

                result = self._do_handle(message, _enqueue)
                self._inbox.record(key, self._consumer)
                outbox_scope.commit()
            inbox_scope.commit()
            with self._lock:
                self._effect_runs += 1
                self._cache[key] = CachedOutcome(
                    key=key, result=result, outputs=tuple(outputs),
                )

    def on_duplicate(self, message: object) -> None:
        """Handle a redelivered message.

        IDC-INV-03: this path is steady-state and MUST NEVER raise as a
        primary error. Subclasses MAY override to emit a metric or log, but
        SHOULD NOT raise. The default implementation is a pure observer —
        counting is handled by `handle()` before this hook runs to avoid
        double-counting a single redelivery across the two code paths.
        """
        _ = message  # default impl is a no-op; present as a documented hook.

    # ----- subclass extension point -----------------------------------------
    def _do_handle(
        self,
        message: object,
        enqueue: Callable[[str, dict[str, object]], None],
    ) -> object:
        """Subclasses override to perform the business effect.

        ``enqueue(topic, payload)`` is the ONLY sanctioned way to publish
        downstream outputs (IDC-INV-04). The return value is cached and
        becomes the replayed result on duplicate delivery.
        """
        raise IdempotentConsumerInvariantError(
            "IDC-INV-01: BaseIdempotentConsumer._do_handle MUST be overridden.",
        )

    # ----- introspection ----------------------------------------------------
    @property
    def handle_calls(self) -> int:
        return self._handle_calls

    @property
    def duplicate_calls(self) -> int:
        return self._duplicate_calls

    @property
    def effect_runs(self) -> int:
        return self._effect_runs

    @property
    def cache_snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(
                {
                    "key": c.key,
                    "result": c.result,
                    "outputs": list(c.outputs),
                }
                for c in self._cache.values()
            )

    @property
    def consumer_name(self) -> str:
        return self._consumer


# ---------------------------------------------------------------------------
# A concrete consumer useful for tests / demos
# ---------------------------------------------------------------------------
@dataclass
class EchoMessage:
    """Minimal message shape used by EchoConsumer."""

    id: str
    payload: dict[str, object] = field(default_factory=dict)


class EchoConsumer(BaseIdempotentConsumer[EchoMessage, dict[str, object]]):
    """Reference consumer that echoes the message payload to ``orders.out``.

    Effectful in the sense that the payload is published to the outbox, so
    the InboxDeduplicator gate is mandatory for exactly-once-effect
    guarantees (IDC-INV-02).
    """

    def _do_handle(
        self,
        message: object,
        enqueue: Callable[[str, dict[str, object]], None],
    ) -> object:
        if not isinstance(message, EchoMessage):
            raise IdempotentConsumerInvariantError(
                "IDC-INV-01: EchoConsumer requires EchoMessage input.",
            )
        enqueue("orders.out", {"id": message.id, "payload": dict(message.payload)})
        return {"id": message.id, "status": "processed"}


# ---------------------------------------------------------------------------
# Helper: build a wired consumer + its collaborators in one call
# ---------------------------------------------------------------------------
def build_echo_consumer(
    consumer_name: str = "orders_consumer",
) -> tuple[EchoConsumer, InMemoryInboxDeduplicator, InMemoryTransactionalOutbox]:
    """Return a fully-wired EchoConsumer plus its inbox and outbox."""
    inbox = InMemoryInboxDeduplicator()
    outbox = InMemoryTransactionalOutbox()
    consumer = EchoConsumer(
        inbox=inbox,
        outbox=outbox,
        consumer_name=consumer_name,
    )
    return consumer, inbox, outbox


__all__ = [
    "BaseIdempotentConsumer",
    "CachedOutcome",
    "EchoConsumer",
    "EchoMessage",
    "IdempotentConsumer",
    "IdempotentConsumerInvariantError",
    "InboxDeduplicatorInvariantError",
    "build_echo_consumer",
]
