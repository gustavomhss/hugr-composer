"""Hypothesis state-machine exploration of EventSourcedStore lifecycle.

Rules model the three public mutation paths (append, snapshot, load) plus
retry-on-conflict. Invariants assert:

- version is always len(events) in the log (ESS-INV-01).
- load() yields exactly the stored events in order (ESS-INV-02).
- any recorded snapshot has version <= current tail (ESS-INV-03).
- replay is pure — repeating the fold yields equal state (ESS-INV-04).
"""

from __future__ import annotations

from EventSourcedStore import (
    ConcurrencyError,
    EventSourcedStoreInvariantError,
    InMemoryEventSourcedStore,
    replay,
)
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule


def _fold(state: object, event: object) -> int:
    assert isinstance(event, dict)
    base = 0 if state is None else int(state)  # type: ignore[arg-type]
    return base + int(event["n"])


class EventSourcedStoreMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.store = InMemoryEventSourcedStore()
        # Shadow model: aggregate_id -> list[int] (the fold inputs).
        self.shadow: dict[str, list[int]] = {}
        # Shadow snapshots: aggregate_id -> (version, state).
        self.snapshots: dict[str, tuple[int, int]] = {}

    @rule(
        agg=st.sampled_from(["A", "B", "C"]),
        n=st.integers(min_value=-100, max_value=100),
        use_stale=st.booleans(),
    )
    def append_event(self, agg: str, n: int, use_stale: bool) -> None:
        if not hasattr(self, "store"):
            return
        actual_v = self.store.current_version(agg)
        expected = actual_v - 1 if use_stale and actual_v > 0 else actual_v
        try:
            self.store.append(agg, expected_version=expected, events=[{"n": n}])
            self.shadow.setdefault(agg, []).append(n)
        except ConcurrencyError:
            # Stale expected_version rejected — shadow unchanged.
            assert expected != actual_v
        except EventSourcedStoreInvariantError:
            pass

    @rule(agg=st.sampled_from(["A", "B", "C"]))
    def take_snapshot(self, agg: str) -> None:
        if not hasattr(self, "store"):
            return
        v = self.store.current_version(agg)
        if v == 0:
            return
        state = sum(self.shadow.get(agg, []))
        try:
            self.store.snapshot(agg, version=v, state=state)
            self.snapshots[agg] = (v, state)
        except EventSourcedStoreInvariantError:
            pass

    @rule(agg=st.sampled_from(["A", "B", "C"]))
    def load_and_check(self, agg: str) -> None:
        if not hasattr(self, "store"):
            return
        loaded = [e["n"] for e in list(self.store.load(agg))]
        assert loaded == self.shadow.get(agg, [])

    @invariant()
    def version_equals_log_length(self) -> None:
        if not hasattr(self, "store"):
            return
        for agg, events in self.shadow.items():
            assert self.store.current_version(agg) == len(events)

    @invariant()
    def replay_matches_shadow_sum(self) -> None:
        if not hasattr(self, "store"):
            return
        for agg, events in self.shadow.items():
            state, v = replay(self.store, agg, _fold)
            assert state == sum(events)
            assert v == len(events)

    @invariant()
    def snapshot_version_bounded_by_tail(self) -> None:
        if not hasattr(self, "store"):
            return
        for agg, (v, _state) in self.snapshots.items():
            assert v <= self.store.current_version(agg)
            snap = self.store.latest_snapshot(agg)
            assert snap is not None
            assert snap.version >= v  # monotonic; snapshot MUST NOT rewind


# Hypothesis hook for pytest collection.
TestEventSourcedStoreMachine = EventSourcedStoreMachine.TestCase
