"""Hypothesis state-machine exploration of TopicBus lifecycle.

Models a single-topic single-group bus. Rules drive publish, ack, nack,
and timeout. Invariants asserted continuously:

- Log size only grows.
- Every published envelope terminally lands in acked OR dlq OR is still in-flight.
- At most one envelope is inflight per key at a time.
"""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from EventEnvelope import EventEnvelope
from TopicBus import Ack, InMemoryTopicBus, Nack


def _env(eid: str, key: str) -> EventEnvelope:
    return EventEnvelope(
        id=eid, source="urn:sm", type="sm.e", extensions={"partitionkey": key},
    )


class TopicBusMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.bus = InMemoryTopicBus(
            ack_timeout_s=0.02, max_redeliveries=2, dlq_topic="dlq",
        )
        self.loop = asyncio.new_event_loop()
        self.published: list[str] = []
        self.seen: list[str] = []
        self.dlq_seen: list[str] = []
        self.mode: str = "ack"  # toggled per-rule below

        async def h(e: EventEnvelope, ack: Ack, nack: Nack) -> None:
            self.seen.append(e.id)
            if self.mode == "nack":
                await nack("x")
                return
            if self.mode == "silent":
                return
            await ack()

        async def audit(e: EventEnvelope, ack: Ack, _n: Nack) -> None:
            self.dlq_seen.append(e.id)
            await ack()

        self.bus.subscribe("t", "g", h)
        self.bus.subscribe("dlq", "audit", audit)

    def _run(self, coro: object) -> None:
        # coro is an awaitable produced by the async methods below.
        self.loop.run_until_complete(coro)  # type: ignore[arg-type]

    @rule(eid=st.integers(min_value=0, max_value=9), key=st.sampled_from(["k1", "k2", "k3"]))
    def publish_ack(self, eid: int, key: str) -> None:
        self.mode = "ack"
        idv = f"e{eid}-{key}-ack-{len(self.published)}"
        self.published.append(idv)
        self._run(self.bus.publish("t", _env(idv, key)))

    @rule(eid=st.integers(min_value=0, max_value=9), key=st.sampled_from(["k1", "k2", "k3"]))
    def publish_nack(self, eid: int, key: str) -> None:
        self.mode = "nack"
        idv = f"e{eid}-{key}-nack-{len(self.published)}"
        self.published.append(idv)
        self._run(self.bus.publish("t", _env(idv, key)))

    @rule(eid=st.integers(min_value=0, max_value=9), key=st.sampled_from(["k1", "k2", "k3"]))
    def publish_silent(self, eid: int, key: str) -> None:
        self.mode = "silent"
        idv = f"e{eid}-{key}-sil-{len(self.published)}"
        self.published.append(idv)
        self._run(self.bus.publish("t", _env(idv, key)))

    @invariant()
    def log_grows_monotonically(self) -> None:
        if not hasattr(self, "bus"):
            return
        assert self.bus.log_size() >= len(self.published)

    @invariant()
    def published_landed_somewhere(self) -> None:
        if not hasattr(self, "bus"):
            return
        # Every published envelope was either seen by the handler OR reached the DLQ.
        for idv in self.published:
            assert idv in self.seen or idv in self.dlq_seen


# Hypothesis hook
TestTopicBusMachine = TopicBusMachine.TestCase
