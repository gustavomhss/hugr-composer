"""CausalReorderBuffer primitive — per-aggregate causal event reordering.

Buffers incoming events keyed by ``(aggregate_id, sequence)``, drains them in
strictly monotonic sequence order, and emits a gap event if a predecessor
fails to arrive before its ``deadline_ms``. After a gap is surfaced, the
buffer skips the missing sequence and continues draining, so a single
dropped message cannot permanently stall an aggregate.

Framework-agnostic: stdlib + typing only. No Flink / Kafka import. OSS
reference is cited in ``CausalReorderBuffer.md`` provenance — the
implementation here is a stdlib-only reimagining of Flink's
out-of-order watermarker and Kafka Streams' out-of-order handling.

Invariant IDs (full text in ``CausalReorderBuffer.md``):

- CRB_INV_01: Events per ``aggregate_id`` drain in strictly monotonic
  sequence order.
- CRB_INV_02: An out-of-order event is held until its predecessor arrives
  OR its ``deadline_ms`` elapses.
- CRB_INV_03: On deadline expiry, ``timed_out()`` emits
  ``(aggregate_id, missing_sequence)`` exactly ONCE.
- CRB_INV_04: After a gap is emitted, events at sequences > missing ARE
  drained (a dropped predecessor does not block the aggregate forever).
- CRB_INV_05: A duplicate ``offer(agg, seq, ...)`` is idempotent — the
  second call is dropped silently.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class CausalReorderBufferError(RuntimeError):
    """Raised when a caller violates the offer contract (bad inputs)."""


@runtime_checkable
class CausalReorderBuffer(Protocol):
    def offer(
        self,
        aggregate_id: str,
        sequence: int,
        event: Mapping[str, Any],
        deadline_ms: int,
    ) -> None: ...
    def next_ready(self, aggregate_id: str) -> Iterator[Mapping[str, Any]]: ...
    def timed_out(self, now_ms: int) -> list[tuple[str, int]]: ...


@dataclass
class _PendingEvent:
    sequence: int
    event: Mapping[str, Any]
    deadline_ms: int


@dataclass
class _AggregateState:
    # next expected sequence — drained events always match this, then +=1.
    next_seq: int = 0
    # sequence -> pending event (sparse holder of out-of-order arrivals).
    pending: dict[int, _PendingEvent] = field(default_factory=dict)
    # set of sequences already observed (for idempotency, INV_05).
    seen: set[int] = field(default_factory=set)
    # gap sequences already reported by timed_out (INV_03 exactly-once).
    reported_gaps: set[int] = field(default_factory=set)


class InMemoryCausalReorderBuffer:
    """Reference buffer. One instance per pipeline stage."""

    def __init__(self, *, start_sequence: int = 0) -> None:
        if start_sequence < 0:
            raise CausalReorderBufferError("start_sequence MUST be >= 0.")
        self._start = start_sequence
        self._aggs: dict[str, _AggregateState] = {}

    # ------------------------------------------------------------------
    # Public Protocol surface
    # ------------------------------------------------------------------
    def offer(
        self,
        aggregate_id: str,
        sequence: int,
        event: Mapping[str, Any],
        deadline_ms: int,
    ) -> None:
        if sequence < 0:
            raise CausalReorderBufferError("sequence MUST be >= 0.")
        st = self._aggs.get(aggregate_id)
        if st is None:
            st = _AggregateState(next_seq=self._start)
            self._aggs[aggregate_id] = st
        # CRB_INV_05: idempotent on duplicates.
        if sequence in st.seen:
            return
        # Events before the current drain head are obsolete — drop.
        if sequence < st.next_seq:
            st.seen.add(sequence)
            return
        st.seen.add(sequence)
        st.pending[sequence] = _PendingEvent(
            sequence=sequence, event=event, deadline_ms=deadline_ms
        )

    def next_ready(self, aggregate_id: str) -> Iterator[Mapping[str, Any]]:
        """Drain every event whose sequence == next_seq contiguously.

        CRB_INV_01: strictly monotonic; yields nothing when head is missing.
        """
        st = self._aggs.get(aggregate_id)
        if st is None:
            return
        while st.next_seq in st.pending:
            pe = st.pending.pop(st.next_seq)
            yield pe.event
            st.next_seq += 1

    def timed_out(self, now_ms: int) -> list[tuple[str, int]]:
        """Return the list of ``(aggregate_id, missing_sequence)`` pairs.

        A pair is emitted when at least one pending event for an aggregate
        has ``deadline_ms <= now_ms`` AND its predecessor
        ``st.next_seq`` is still missing. CRB_INV_03 ensures each gap is
        reported exactly once; CRB_INV_04 advances ``next_seq`` past the
        reported gap so subsequent events can drain.
        """
        gaps: list[tuple[str, int]] = []
        for agg_id, st in self._aggs.items():
            # Iterate while the head is missing AND some descendant has expired.
            while st.next_seq not in st.pending and st.pending:
                descendants_expired = any(
                    pe.deadline_ms <= now_ms for pe in st.pending.values()
                )
                if not descendants_expired:
                    break
                missing = st.next_seq
                if missing not in st.reported_gaps:
                    st.reported_gaps.add(missing)
                    gaps.append((agg_id, missing))
                # CRB_INV_04: advance past the gap so later events drain.
                st.next_seq += 1
        return gaps


__all__ = [
    "CausalReorderBuffer",
    "CausalReorderBufferError",
    "InMemoryCausalReorderBuffer",
]
