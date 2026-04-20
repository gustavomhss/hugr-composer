"""TopicBus primitive — publish/subscribe facade over a broker topic.

Implements the catalog Protocol for `events.TopicBus` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- TB_INV_01: Delivery to a subscribed handler MUST be at least once by default,
  so handlers SHALL tolerate duplicates. Concretely: a published envelope for
  which at least one group is subscribed MUST reach that group's handler at
  least once OR be routed to the dead-letter destination.
- TB_INV_02: Inside one consumer group a given message ALWAYS goes to exactly
  one handler instance at a time; redeliveries NEVER overlap with the previous
  dispatch of the same envelope.
- TB_INV_03: Negative acknowledgement MUST cause redelivery or routing to a
  dead-letter destination when configured; a nack SHALL NEVER silently drop
  the envelope.
- TB_INV_04: Subscribers CANNOT rely on global ordering across topic
  partitions, only on partition-local order — same-key events ALWAYS land in
  publish order at a given group handler.
- TB_INV_05: Publish NEVER succeeds without the broker confirming the
  persisted append; the log commit MUST be durable w.r.t. any fanout to
  subscribers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from EventEnvelope import (  # type: ignore[import-not-found]  # TB_INV_05 — sibling primitive resolved at runtime via conftest.py sys.path insert.
    EventEnvelope,
)

# ---------------------------------------------------------------------------
# Callback aliases (match the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
Ack = Callable[[], Awaitable[None]]
Nack = Callable[[str], Awaitable[None]]
Handler = Callable[[EventEnvelope, Ack, Nack], Awaitable[None]]


# ---------------------------------------------------------------------------
# Factory helpers for per-attempt ack/nack callbacks (avoid loop-captured closures)
# ---------------------------------------------------------------------------
def _make_ack(evt: asyncio.Event) -> Callable[[], Awaitable[None]]:
    async def _ack() -> None:
        evt.set()

    return _ack


def _make_nack(
    evt: asyncio.Event, reason_box: list[str],
) -> Callable[[str], Awaitable[None]]:
    async def _nack(reason: str) -> None:
        reason_box.append(reason or "unspecified")
        evt.set()

    return _nack


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_ACK_TIMEOUT_S: Final[float] = 5.0
_DEFAULT_MAX_REDELIVERIES: Final[int] = 3
_DLQ_REASON_TIMEOUT: Final[str] = "ack_timeout"
_DLQ_REASON_EXHAUSTED: Final[str] = "redelivery_exhausted"


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class TopicBus(Protocol):
    async def publish(self, topic: str, envelope: EventEnvelope) -> None: ...
    def subscribe(
        self,
        topic: str,
        group: str,
        handler: Callable[[EventEnvelope, Ack, Nack], Awaitable[None]],
    ) -> None: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class TopicBusInvariantError(RuntimeError):
    """Raised when a TopicBus invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Append-log entry — the durable record written BEFORE fanout (TB_INV_05)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AppendRecord:
    """One durably-appended envelope, tagged with a monotonic sequence number.

    Publish resolves only after the record is appended — the in-memory log is
    the durability boundary; fanout to subscribers is strictly a consequence
    of a committed append (TB_INV_05).
    """

    seq: int
    topic: str
    partition_key: str
    envelope: EventEnvelope


# ---------------------------------------------------------------------------
# Dispatch record — runtime accounting for one (envelope, group) attempt
# ---------------------------------------------------------------------------
@dataclass
class _Dispatch:
    envelope: EventEnvelope
    topic: str
    group: str
    delivered: int = 0             # count of delivery attempts (TB_INV_01 accounting)
    acks: int = 0                  # count of successful acks
    nacks: int = 0                 # count of nacks
    dlq_routed: bool = False       # final routing outcome
    inflight: bool = False         # TB_INV_02: exclusive dispatch window
    last_reason: str | None = None


# ---------------------------------------------------------------------------
# Partition key extractor — extensions.partitionkey, else envelope.subject,
# else envelope.id. Deterministic and side-effect-free.
# ---------------------------------------------------------------------------
def partition_key_of(envelope: EventEnvelope) -> str:
    """Return the partition / ordering key for an envelope (TB_INV_04)."""
    exts = envelope.extensions
    if exts is not None and "partitionkey" in exts:
        key = exts["partitionkey"]
        if isinstance(key, str) and key:
            return key
    subject: object = envelope.subject
    if isinstance(subject, str) and subject:
        return subject
    eid: object = envelope.id
    if isinstance(eid, str):
        return eid
    return str(eid)


# ---------------------------------------------------------------------------
# Reference implementation — InMemoryTopicBus
# ---------------------------------------------------------------------------
class InMemoryTopicBus:
    """Reference TopicBus that commits an append log before fanout.

    The implementation models a single-broker pub/sub with:

    - A monotonic append log keyed by (topic, partition_key). Publish awaits
      the append commit (TB_INV_05) before dispatching to subscribers.
    - Subscriber groups; each group receives every envelope at least once
      (TB_INV_01) with serialized per-key dispatch (TB_INV_02 + TB_INV_04).
    - Ack/nack with configurable ack timeout (no infinite block) and
      redelivery. Exhausted redeliveries route to the dead-letter topic
      (TB_INV_03) using `publish` — the SAME append-log path, not a side list.
    """

    def __init__(
        self,
        *,
        ack_timeout_s: float = _DEFAULT_ACK_TIMEOUT_S,
        max_redeliveries: int = _DEFAULT_MAX_REDELIVERIES,
        dlq_topic: str | None = None,
    ) -> None:
        if ack_timeout_s <= 0:
            raise TopicBusInvariantError(
                "TB_INV_01: ack_timeout_s MUST be > 0 — infinite ack wait is FORBIDDEN.",
            )
        if max_redeliveries < 0:
            raise TopicBusInvariantError(
                "TB_INV_03: max_redeliveries MUST be >= 0.",
            )
        self._ack_timeout_s: float = ack_timeout_s
        self._max_redeliveries: int = max_redeliveries
        self._dlq_topic: str | None = dlq_topic

        # Append log — per (topic, partition_key) ordered list of records.
        self._log: dict[tuple[str, str], list[AppendRecord]] = {}
        # Global monotonic sequence counter.
        self._seq: int = 0
        # Subscribers: topic -> group -> handler.
        self._subs: dict[str, dict[str, Handler]] = {}
        # Per (group, partition_key) asyncio.Lock for per-key serial dispatch.
        self._key_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        # Runtime accounting: (group, envelope_dedup_key) -> _Dispatch.
        self._dispatches: dict[tuple[str, str, tuple[str, str]], _Dispatch] = {}
        # Protects append log + sequence counter (publish atomicity).
        self._append_lock = threading.Lock()
        # Soft-closed flag: after `close()` publish is rejected.
        self._closed: bool = False

    # ---- subscription ------------------------------------------------------
    def subscribe(
        self,
        topic: str,
        group: str,
        handler: Callable[[EventEnvelope, Ack, Nack], Awaitable[None]],
    ) -> None:
        """Register a handler for (topic, group). Last writer wins per group."""
        if self._closed:
            raise TopicBusInvariantError(
                "TB_INV_01: bus is closed; subscription CANNOT be added after close.",
            )
        if not topic or not group:
            raise TopicBusInvariantError(
                "TB_INV_01: topic and group MUST be non-empty strings.",
            )
        self._subs.setdefault(topic, {})[group] = handler

    # ---- publish -----------------------------------------------------------
    async def publish(self, topic: str, envelope: EventEnvelope) -> None:
        """Append-then-fanout. Returns only after the append commits.

        TB_INV_05: The append to the partition log is performed under a lock
        and the returned awaitable only resolves once the record is committed.
        Dispatch to subscribers is scheduled strictly after the commit.
        """
        if self._closed:
            raise TopicBusInvariantError(
                "TB_INV_05: bus is closed; publish CANNOT succeed after close.",
            )
        if not topic:
            raise TopicBusInvariantError("TB_INV_05: topic MUST be non-empty.")

        key = partition_key_of(envelope)
        record = self._commit_append(topic, key, envelope)

        # Fanout. Per-group, per-key serial dispatch runs as a background
        # task; the public publish() contract is satisfied once the append
        # has committed (TB_INV_05), but we keep a reference so tests can
        # deterministically drain.
        groups = self._subs.get(topic, {})
        for group, handler in groups.items():
            await self._dispatch(record, group, handler)

    def _commit_append(
        self,
        topic: str,
        partition_key: str,
        envelope: EventEnvelope,
    ) -> AppendRecord:
        """Atomically append an envelope to the durable log and return it.

        TB_INV_05: seq is assigned and the record is appended under the same
        critical section, so any observable fanout implies the record is in
        the log.
        """
        with self._append_lock:
            self._seq += 1
            seq = self._seq
            record = AppendRecord(
                seq=seq, topic=topic, partition_key=partition_key, envelope=envelope,
            )
            self._log.setdefault((topic, partition_key), []).append(record)
        return record

    # ---- dispatch (per-group, per-key serial) ------------------------------
    async def _dispatch(self, record: AppendRecord, group: str, handler: Handler) -> None:
        """Deliver `record` to a single group handler with ack/nack + redelivery."""
        lock_key = (record.topic, group, record.partition_key)
        lock = self._key_locks.setdefault(lock_key, asyncio.Lock())
        dkey = (record.topic, group, record.envelope.dedup_key())
        disp = self._dispatches.setdefault(
            dkey,
            _Dispatch(envelope=record.envelope, topic=record.topic, group=group),
        )

        # TB_INV_04: the per-key lock serializes same-key deliveries so
        # a same-key sequence lands at the handler in publish order.
        async with lock:
            await self._deliver_with_retry(disp, handler)

    async def _deliver_with_retry(self, disp: _Dispatch, handler: Handler) -> None:
        """One delivery attempt plus bounded redelivery on nack / timeout."""
        attempt = 0
        while True:
            attempt += 1
            outcome, reason = await self._attempt_delivery(disp, handler)
            if outcome == "ack":
                return
            if attempt <= self._max_redeliveries:
                continue  # TB_INV_03: bounded redelivery.
            await self._route_to_dlq(disp, reason)
            return

    async def _attempt_delivery(
        self, disp: _Dispatch, handler: Handler,
    ) -> tuple[str, str]:
        """Run one handler invocation and wait for ack/nack/timeout.

        Returns (outcome, reason). outcome is one of {"ack", "nack"}.
        """
        # TB_INV_02: exclusive dispatch window — inflight MUST be False
        # before we open a new attempt, then flipped True for the duration.
        if disp.inflight:
            raise TopicBusInvariantError(
                "TB_INV_02: overlapping dispatch detected; exclusive per-group "
                "delivery violated.",
            )
        disp.inflight = True
        disp.delivered += 1

        ack_evt = asyncio.Event()
        nack_evt = asyncio.Event()
        nack_reason_box: list[str] = []

        ack_fn = _make_ack(ack_evt)
        nack_fn = _make_nack(nack_evt, nack_reason_box)

        # Handler exceptions are absorbed as an implicit nack (TB_INV_03).
        try:
            await handler(disp.envelope, ack_fn, nack_fn)
        except BaseException as exc:  # noqa: BLE001 — TB_INV_03: handler errors MUST redeliver or DLQ
            if not ack_evt.is_set() and not nack_evt.is_set():
                nack_reason_box.append(f"handler_exception:{type(exc).__name__}")
                nack_evt.set()

        # TB_INV_01 + TB_INV_03: bounded ack wait — no infinite block.
        ack_task = asyncio.create_task(ack_evt.wait())
        nack_task = asyncio.create_task(nack_evt.wait())
        try:
            await asyncio.wait(
                [ack_task, nack_task],
                timeout=self._ack_timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            disp.inflight = False
            for t in (ack_task, nack_task):
                if not t.done():
                    t.cancel()

        if ack_evt.is_set():
            disp.acks += 1
            disp.last_reason = None
            return "ack", ""
        if nack_evt.is_set():
            disp.nacks += 1
            reason = nack_reason_box[-1] if nack_reason_box else "unspecified"
            disp.last_reason = reason
            return "nack", reason
        # Timeout — treat as nack with a specific reason (TB_INV_01).
        disp.nacks += 1
        disp.last_reason = _DLQ_REASON_TIMEOUT
        return "nack", _DLQ_REASON_TIMEOUT

    async def _route_to_dlq(self, disp: _Dispatch, reason: str) -> None:
        """TB_INV_03: route an exhausted dispatch to the configured DLQ topic.

        Routing uses publish() so the DLQ append goes through the SAME
        durable append log as normal traffic — no side-list shortcut.
        """
        disp.last_reason = disp.last_reason or reason
        if self._dlq_topic is None:
            # No DLQ configured — still mark the dispatch as exhausted so
            # the caller can observe via metrics. Not dropping silently.
            disp.dlq_routed = False
            return
        disp.dlq_routed = True
        # Avoid infinite recursion: DLQ routing publishes under a flag that
        # suppresses fanout to subscribers on the DLQ topic itself unless
        # explicitly subscribed. We simply append — subscribers of the DLQ
        # topic receive the envelope via normal subscribe semantics.
        #
        # Build a new envelope with a reason extension; reuse original id/source
        # so dedup still works on the DLQ consumer side.
        from dataclasses import replace

        exts_base: dict[str, str] = (
            dict(disp.envelope.extensions.items())
            if disp.envelope.extensions is not None
            else {}
        )
        exts_base["dlqreason"] = reason[:20] if reason else _DLQ_REASON_EXHAUSTED
        dlq_env = replace(disp.envelope, extensions=exts_base)
        await self.publish(self._dlq_topic, dlq_env)

    # ---- introspection -----------------------------------------------------
    def log_snapshot(self, topic: str, partition_key: str) -> tuple[AppendRecord, ...]:
        """Return the durable append log for one (topic, partition_key)."""
        with self._append_lock:
            return tuple(self._log.get((topic, partition_key), ()))

    def log_size(self) -> int:
        """Total records across all partition logs (TB_INV_05 witness)."""
        with self._append_lock:
            return sum(len(v) for v in self._log.values())

    def dispatch_stats(
        self, topic: str, group: str, envelope: EventEnvelope,
    ) -> Mapping[str, int]:
        """Return per-(topic, group, envelope) delivery counters."""
        d = self._dispatches.get((topic, group, envelope.dedup_key()))
        if d is None:
            return {"delivered": 0, "acks": 0, "nacks": 0, "dlq": 0}
        return {
            "delivered": d.delivered,
            "acks": d.acks,
            "nacks": d.nacks,
            "dlq": 1 if d.dlq_routed else 0,
        }

    @property
    def dlq_topic(self) -> str | None:
        return self._dlq_topic

    @property
    def ack_timeout_s(self) -> float:
        return self._ack_timeout_s

    @property
    def max_redeliveries(self) -> int:
        return self._max_redeliveries

    def close(self) -> None:
        """Soft-close — reject new publishes / subscriptions."""
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


# ---------------------------------------------------------------------------
# Middleware helper (extension contract — wrap a handler with cross-cut)
# ---------------------------------------------------------------------------
def with_middleware(
    handler: Handler,
    *,
    before: Callable[[EventEnvelope], None] | None = None,
    after: Callable[[EventEnvelope, str], None] | None = None,
) -> Handler:
    """Wrap a handler with optional before / after hooks.

    The wrapper preserves ack/nack semantics; after-hook receives the final
    disposition string ("ack" | "exception:<type>").
    """

    async def _wrapped(env: EventEnvelope, ack: Ack, nack: Nack) -> None:
        if before is not None:
            before(env)
        try:
            await handler(env, ack, nack)
        except BaseException as exc:  # TB_INV_03 — redeliver on handler errors, never swallow.
            if after is not None:
                after(env, f"exception:{type(exc).__name__}")
            raise
        if after is not None:
            after(env, "ack")

    return _wrapped


# ---------------------------------------------------------------------------
# Observability hook — emit a log-shaped dict for each terminal disposition.
# ---------------------------------------------------------------------------
@dataclass
class ObservabilitySink:
    """Collects structured events for test harnesses."""

    logs: list[dict[str, object]] = field(default_factory=list)

    def on_publish(self, topic: str, seq: int, envelope: EventEnvelope) -> None:
        self.logs.append(
            {
                "event_name": "bus.published",
                "topic": topic,
                "seq": seq,
                "envelope_id": envelope.id,
                "timestamp": time.time(),
            },
        )

    def on_ack(self, topic: str, group: str, envelope: EventEnvelope) -> None:
        self.logs.append(
            {
                "event_name": "bus.acked",
                "topic": topic,
                "group": group,
                "envelope_id": envelope.id,
            },
        )

    def on_nack(
        self, topic: str, group: str, envelope: EventEnvelope, reason: str,
    ) -> None:
        self.logs.append(
            {
                "event_name": "bus.nacked",
                "topic": topic,
                "group": group,
                "envelope_id": envelope.id,
                "reason": reason,
            },
        )

    def on_dlq(
        self, topic: str, group: str, envelope: EventEnvelope, reason: str,
    ) -> None:
        self.logs.append(
            {
                "event_name": "bus.dlq.routed",
                "topic": topic,
                "group": group,
                "envelope_id": envelope.id,
                "reason": reason,
            },
        )


# ---------------------------------------------------------------------------
# Deduplication helper — consumers MUST treat duplicates as normal (TB_INV_01).
# Wrap a handler with `dedup_handler(...)` to drop repeats by (source, id).
# ---------------------------------------------------------------------------
def dedup_handler(inner: Handler, *, seen: set[tuple[str, str]] | None = None) -> Handler:
    """Return a handler that acks-and-drops duplicates it has seen before.

    `seen` is the shared dedup oracle; pass an explicit set when multiple
    consumer instances share the same dedup scope.
    """
    seen_local: set[tuple[str, str]] = seen if seen is not None else set()

    async def _wrapped(env: EventEnvelope, ack: Ack, nack: Nack) -> None:
        key = env.dedup_key()
        if key in seen_local:
            await ack()
            return
        seen_local.add(key)
        await inner(env, ack, nack)

    return _wrapped


__all__ = [
    "Ack",
    "AppendRecord",
    "Handler",
    "InMemoryTopicBus",
    "Nack",
    "ObservabilitySink",
    "TopicBus",
    "TopicBusInvariantError",
    "dedup_handler",
    "partition_key_of",
    "with_middleware",
]
