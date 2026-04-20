"""Hypothesis state-machine exploration of the DomainEvent aggregate stream.

Explores all reachable states of the (stage → flush | discard) lifecycle for a
single aggregate, confirming DE-INV-02 and DE-INV-04 hold under any ordering.
"""

from __future__ import annotations

from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from DomainEvent import (
    AggregateEventStream,
    AggregateStreamError,
    FrozenDomainEvent,
)
from test_DomainEvent import make_event, uuid_v7


class DomainEventStreamMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.stream = AggregateEventStream()
        self.published: list[FrozenDomainEvent] = []
        # Model state: last flushed version + staged count per aggregate.
        self.last_version = 0
        self.pending_count = 0
        self.seen_event_ids: set[str] = set()

    AGG_ID = "sm-agg"

    @rule()
    def stage_valid(self) -> None:
        if not hasattr(self, "stream"):
            return
        expected = self.last_version + self.pending_count + 1
        evt = make_event(version=expected, aggregate_id=self.AGG_ID)
        self.stream.stage(evt)
        self.pending_count += 1
        self.seen_event_ids.add(evt.event_id)

    @rule()
    def stage_duplicate_version_rejected(self) -> None:
        if not hasattr(self, "stream"):
            return
        issued = self.last_version + self.pending_count
        if issued == 0:
            return
        # Re-staging any already-issued version MUST be rejected on the SAME aggregate.
        v = issued
        try:
            self.stream.stage(
                make_event(version=v, event_id=uuid_v7(), aggregate_id=self.AGG_ID),
            )
        except AggregateStreamError:
            return
        raise AssertionError(f"duplicate version {v} accepted at issued={issued}")

    @rule()
    def flush_op(self) -> None:
        if not hasattr(self, "stream"):
            return
        self.stream.flush(self.published.append)
        self.last_version += self.pending_count
        self.pending_count = 0

    @rule()
    def discard_op(self) -> None:
        if not hasattr(self, "stream"):
            return
        self.stream.discard()
        self.pending_count = 0

    @invariant()
    def published_versions_are_monotonic(self) -> None:
        if not hasattr(self, "stream"):
            return
        versions = [p.version for p in self.published]
        # Published versions MUST be 1, 2, 3, ... contiguously (DE-INV-04).
        assert versions == list(range(1, len(versions) + 1)), versions

    @invariant()
    def event_ids_unique(self) -> None:
        if not hasattr(self, "stream"):
            return
        ids = [p.event_id for p in self.published]
        assert len(ids) == len(set(ids))


# Hypothesis hook
TestDomainEventStreamMachine = DomainEventStreamMachine.TestCase
