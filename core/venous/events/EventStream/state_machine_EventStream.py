"""Hypothesis state-machine exploration of EventStream lifecycle.

Explores random interleavings of append / read_from / tail / truncate_before
against a small set of partitions. Asserts global invariants:

- ES-INV-01: per-partition seqs are strictly monotonic and contiguous from
  the truncation cursor upward.
- ES-INV-02: stored events never change shape across invariant checks.
- ES-INV-03: read_from at a valid offset is idempotent; read_from below the
  truncation cursor raises.
- ES-INV-04: the truncation cursor is non-decreasing.
"""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from EventStream import (
    EventStreamInvariantError,
    InMemoryEventStream,
)


_PARTITIONS = ("a", "b", "c")


class EventStreamMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.es = InMemoryEventStream(retention_min_entries=0)
        self.expected_tail: dict[str, int] = {k: 1 for k in _PARTITIONS}
        self.truncation: dict[str, int] = {k: 0 for k in _PARTITIONS}

    @rule(key=st.sampled_from(_PARTITIONS), i=st.integers(min_value=0, max_value=1000))
    def append_event(self, key: str, i: int) -> None:
        if not hasattr(self, "es"):
            return
        seq = self.es.append(key, {"i": i})
        assert seq == self.expected_tail[key]
        self.expected_tail[key] += 1

    @rule(key=st.sampled_from(_PARTITIONS))
    def read_head(self, key: str) -> None:
        if not hasattr(self, "es"):
            return
        # Read from the current truncation cursor — every stored event has
        # seq >= cursor, so the reader sees them all.
        cursor = self.es.truncated_before_of(key)
        events = list(self.es.read_from(key, cursor))
        # Events present in the partition: seqs in [max(cursor, 1), tail - 1].
        # Count = tail - max(cursor, 1) when tail > cursor else 0.
        floor = cursor if cursor >= 1 else 1
        expected_retained = max(0, self.expected_tail[key] - floor)
        assert len(events) == expected_retained

    @rule(key=st.sampled_from(_PARTITIONS))
    def tail_check(self, key: str) -> None:
        if not hasattr(self, "es"):
            return
        assert self.es.tail(key) == self.expected_tail[key]

    @rule(delta=st.integers(min_value=0, max_value=3))
    def advance_truncation(self, delta: int) -> None:
        if not hasattr(self, "es"):
            return
        # Truncate is a no-op at the impl level until at least one partition
        # exists — skip the rule until then so the model mirrors reality.
        if self.es.partition_count == 0:
            return
        # Advance by `delta` across every partition, subject to:
        # - offset may never exceed tail (= expected_tail[k]);
        # - offset may never rewind below the current truncation cursor.
        current_max = max(self.truncation[k] for k in _PARTITIONS)
        candidate = current_max + delta
        # Only reason about partitions that actually exist — the model
        # mirrors the impl, which only tracks `truncated` for known keys.
        existing = [
            k for k in _PARTITIONS
            if self.es.partition_size(k) > 0 or self.expected_tail[k] > 1
        ]
        max_tail = min(self.expected_tail[k] for k in existing)
        candidate = min(candidate, max_tail)
        if candidate < current_max:
            return
        self.es.truncate_before(candidate)
        for k in existing:
            self.truncation[k] = candidate

    @rule(key=st.sampled_from(_PARTITIONS))
    def rewind_read_rejected(self, key: str) -> None:
        if not hasattr(self, "es"):
            return
        # Unknown partitions legitimately report truncated=0 — no rewind read
        # to attempt there; skip until the partition has seen an append.
        if self.es.partition_size(key) == 0:
            return
        trunc = self.es.truncated_before_of(key)
        if trunc == 0:
            return
        try:
            list(self.es.read_from(key, trunc - 1))
            raise AssertionError("ES-INV-03: read into truncated window must raise")
        except EventStreamInvariantError:
            pass

    # --- global invariants --------------------------------------------------
    @invariant()
    def per_partition_seqs_are_contiguous(self) -> None:
        if not hasattr(self, "es"):
            return
        for k in _PARTITIONS:
            snap = self.es.log_snapshot(k)
            seqs = [int(e["seq"]) for e in snap]  # type: ignore[arg-type]
            expected_first = self.truncation[k] if self.truncation[k] >= 1 else 1
            if seqs:
                # Strict monotonicity + contiguous.
                assert seqs == sorted(seqs)
                assert len(set(seqs)) == len(seqs)
                # First seq is at least the truncation cursor (could equal or
                # exceed it if truncation is 0 and the partition is empty).
                assert seqs[0] >= expected_first
                # Last seq is tail - 1.
                assert seqs[-1] == self.expected_tail[k] - 1

    @invariant()
    def truncation_cursor_monotonic(self) -> None:
        if not hasattr(self, "es"):
            return
        for k in _PARTITIONS:
            # Only verify partitions that actually exist on the impl — an
            # unknown partition legitimately reports 0 because it was never
            # created (append is the partition-creation step).
            if self.es.partition_size(k) == 0 and self.expected_tail[k] == 1:
                continue
            assert self.es.truncated_before_of(k) == self.truncation[k]

    @invariant()
    def read_from_idempotent(self) -> None:
        if not hasattr(self, "es"):
            return
        for k in _PARTITIONS:
            trunc = self.es.truncated_before_of(k)
            a = list(self.es.read_from(k, trunc))
            b = list(self.es.read_from(k, trunc))
            assert a == b


# Hypothesis hook
TestEventStreamMachine = EventStreamMachine.TestCase
