"""Exactly-once on a weak broker — causal buffer + idempotent consumer."""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class BrokerEvent:
    event_id: str
    aggregate_id: str
    seq: int
    payload: dict


class IdempotentConsumer:
    """At-most-once per event_id; dedup state persists in a DB-like set."""

    def __init__(self, handler: Callable[[BrokerEvent], None]) -> None:
        self._handler = handler
        self._applied: set[str] = set()
        self._lock = threading.Lock()

    def deliver(self, event: BrokerEvent) -> bool:
        with self._lock:
            if event.event_id in self._applied:
                return False
        self._handler(event)
        with self._lock:
            self._applied.add(event.event_id)
        return True

    @property
    def applied(self) -> set[str]:
        with self._lock:
            return set(self._applied)


@dataclass
class GapRecord:
    aggregate_id: str
    missing_seq: int
    timed_out_at: float


class CausalReorderBuffer:
    """Per-aggregate reorder buffer.

    `offer(event, now)` queues it; `drain(now)` emits events in strict
    causal order (seq starting at `next_seq`). If `now - first_queued_at`
    exceeds `gap_timeout_s`, emits a gap record and advances `next_seq`.
    """

    def __init__(self, consumer: IdempotentConsumer, *, gap_timeout_s: float = 5.0) -> None:
        self._consumer = consumer
        self.gap_timeout_s = gap_timeout_s
        self._pending: dict[str, dict[int, tuple[BrokerEvent, float]]] = defaultdict(dict)
        self._next_seq: dict[str, int] = defaultdict(lambda: 1)
        self.gaps: list[GapRecord] = []
        self._lock = threading.Lock()

    def offer(self, event: BrokerEvent, *, now: float) -> None:
        with self._lock:
            # If already applied by the consumer, drop silently.
            if event.event_id in self._consumer.applied:
                return
            slot = self._pending[event.aggregate_id]
            if event.seq not in slot:
                slot[event.seq] = (event, now)

    def drain(self, *, now: float) -> int:
        """Deliver everything ready; returns count delivered."""
        delivered = 0
        with self._lock:
            for agg, slot in list(self._pending.items()):
                while True:
                    nxt = self._next_seq[agg]
                    if nxt in slot:
                        ev, _ts = slot.pop(nxt)
                        self._consumer.deliver(ev)
                        self._next_seq[agg] = nxt + 1
                        delivered += 1
                        continue
                    # Nothing at nxt — check for gap timeout.
                    if slot:
                        earliest_seq = min(slot)
                        _ev, ts = slot[earliest_seq]
                        if now - ts >= self.gap_timeout_s:
                            # Record gap for missing seq nxt, skip forward.
                            self.gaps.append(GapRecord(
                                aggregate_id=agg, missing_seq=nxt,
                                timed_out_at=now,
                            ))
                            self._next_seq[agg] = earliest_seq
                            continue
                    break
        return delivered
