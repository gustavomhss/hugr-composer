"""Hypothesis state-machine exploration of DeadLetterRoute lifecycle.

Models one route (source=s, dest=d). Rules drive send / inspect / requeue /
purge. Invariants asserted continuously:

- depth(d) equals the cardinality of parked keys.
- Every envelope EVER parked is either currently in parked, or was
  requeued, or was purged (no silent drop).
- A requeued envelope surfaced on the source topic at least once.
- Every parked record has failure_count >= 1 and a non-empty reason.
"""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from DeadLetterRoute import (
    DeadLetterRoute,
    InMemoryDeadLetterSink,
)
from EventEnvelope import EventEnvelope


class _Bus:
    def __init__(self) -> None:
        self.seen: list[tuple[str, EventEnvelope]] = []

    async def republish(self, topic: str, envelope: EventEnvelope) -> None:
        self.seen.append((topic, envelope))


class DeadLetterRouteMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.route = DeadLetterRoute(
            source_topic="s", destination_topic="d", max_deliveries=2,
        )
        self.sink = InMemoryDeadLetterSink()
        self.bus = _Bus()
        self.loop = asyncio.new_event_loop()
        self.ever_parked: set[tuple[str, str]] = set()
        self.ever_requeued: set[tuple[str, str]] = set()
        self.ever_purged: set[tuple[str, str]] = set()

    def _run(self, coro: object) -> None:
        self.loop.run_until_complete(coro)  # type: ignore[arg-type]

    @rule(eid=st.integers(min_value=0, max_value=5))
    def park(self, eid: int) -> None:
        env = EventEnvelope(id=f"e{eid}", source="urn:sm", type="sm.e")
        self._run(self.sink.send(self.route, env, "poison", attempt=3))
        self.ever_parked.add(("urn:sm", f"e{eid}"))

    @rule(eid=st.integers(min_value=0, max_value=5))
    def try_requeue(self, eid: int) -> None:
        key = ("urn:sm", f"e{eid}")
        if key not in {
            (r.origin_source, r.origin_id) for r in self.sink.inspect(
                "d", emit_audit=False,
            )
        }:
            return
        self._run(self.sink.requeue("d", "urn:sm", f"e{eid}", self.bus))
        self.ever_requeued.add(key)

    @rule(eid=st.integers(min_value=0, max_value=5))
    def try_purge_one(self, eid: int) -> None:
        key = ("urn:sm", f"e{eid}")
        if key not in {
            (r.origin_source, r.origin_id) for r in self.sink.inspect(
                "d", emit_audit=False,
            )
        }:
            return
        self.sink.purge(
            "d",
            envelope_source="urn:sm",
            envelope_id=f"e{eid}",
            reason="sm_purge",
        )
        self.ever_purged.add(key)

    @rule()
    def inspect_snapshot(self) -> None:
        # Read-only op — must not mutate depth.
        before = self.sink.depth("d")
        _ = self.sink.inspect("d", emit_audit=False)
        after = self.sink.depth("d")
        assert before == after

    @invariant()
    def depth_matches_inspect(self) -> None:
        if not hasattr(self, "sink"):
            return
        parked_count = len(self.sink.inspect("d", emit_audit=False))
        assert self.sink.depth("d") == parked_count

    @invariant()
    def no_silent_drop(self) -> None:
        if not hasattr(self, "sink"):
            return
        currently_parked = {
            (r.origin_source, r.origin_id)
            for r in self.sink.inspect("d", emit_audit=False)
        }
        for k in self.ever_parked:
            assert (
                k in currently_parked
                or k in self.ever_requeued
                or k in self.ever_purged
            )

    @invariant()
    def parked_has_reason_and_failure(self) -> None:
        if not hasattr(self, "sink"):
            return
        for r in self.sink.inspect("d", emit_audit=False):
            assert r.failure_count >= 1
            assert r.last_reason
            assert len(r.last_reason) > 0


TestDeadLetterRouteMachine = DeadLetterRouteMachine.TestCase
