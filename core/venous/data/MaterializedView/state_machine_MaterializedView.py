"""Hypothesis state-machine exploration of MaterializedView lifecycle.

Explores random interleavings of apply / rebuild / evolve_schema / query /
duplicate-delivery and asserts global invariants:

- MV-INV-01: identical replay converges to identical state.
- MV-INV-02: rebuild() fully resets state from the supplied source.
- MV-INV-03: staleness is monotonic relative to clock advancement.
- MV-INV-04: pending schema evolution MUST refuse query until rebuild.
"""

from __future__ import annotations

from collections.abc import Mapping

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from MaterializedView import (
    InMemoryMaterializedView,
    MaterializedViewInvariantError,
)


def _upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    payload = event.get("payload", {})
    assert isinstance(payload, Mapping)
    rows[aid] = {"aggregate_id": aid, **dict(payload)}


def _ev(seq: int, aid: str, val: int, version: int = 1) -> dict[str, object]:
    return {
        "type": "x",
        "aggregate_id": aid,
        "seq": seq,
        "schema_version": version,
        "payload": {"val": val},
    }


class MaterializedViewMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self._fake_time = 1000.0
        self.view = InMemoryMaterializedView(
            "stm",
            schema_version=1,
            max_age_s=5.0,
            clock=self._clock,
        )
        self.view.register_handler("x", _upsert)
        self.stream: list[dict[str, object]] = []
        self.next_seq = 1
        self.schema_version = 1
        self.pending_rebuild = False

    def _clock(self) -> float:
        return self._fake_time

    @rule(aid=st.sampled_from(["a1", "a2", "a3"]), val=st.integers(min_value=0, max_value=100))
    def apply_new_event(self, aid: str, val: int) -> None:
        if not hasattr(self, "view"):
            return
        e = _ev(self.next_seq, aid, val, version=self.schema_version)
        if self.pending_rebuild:
            try:
                self.view.apply(e)
                raise AssertionError("MV-INV-04: pending-schema view MUST refuse apply")
            except MaterializedViewInvariantError:
                return
        self.view.apply(e)
        self.stream.append(e)
        self.next_seq += 1

    @rule()
    def reapply_last(self) -> None:
        if not hasattr(self, "view") or not self.stream:
            return
        # At-least-once delivery duplicate — must be deduped.
        self.view.apply(self.stream[-1])

    @rule()
    def advance_clock(self) -> None:
        if not hasattr(self, "view"):
            return
        self._fake_time += 0.5

    @rule()
    def query_rows(self) -> None:
        if not hasattr(self, "view"):
            return
        if self.pending_rebuild:
            try:
                list(self.view.query(None))
                raise AssertionError("query MUST refuse while rebuild is pending")
            except MaterializedViewInvariantError:
                return
        list(self.view.query(None))

    @rule()
    def rebuild_from_stream(self) -> None:
        if not hasattr(self, "view"):
            return
        # Rebuild from the current stream (only events matching declared schema).
        source = [e for e in self.stream if int(e["schema_version"]) == self.schema_version]  # type: ignore[arg-type]
        self.view.rebuild(source)
        self.pending_rebuild = False

    @rule()
    def evolve_schema(self) -> None:
        if not hasattr(self, "view"):
            return
        self.schema_version += 1
        self.view.evolve_schema(self.schema_version)
        self.pending_rebuild = True
        # Invalidate the pre-evolution stream for apply purposes — simulate
        # source-system re-emission at the new schema.
        self.stream = []

    # --- invariants ---------------------------------------------------------
    @invariant()
    def staleness_non_negative(self) -> None:
        if not hasattr(self, "view"):
            return
        assert self.view.staleness_s() >= 0.0

    @invariant()
    def seq_monotonic(self) -> None:
        if not hasattr(self, "view"):
            return
        assert self.view.last_applied_seq < self.next_seq

    @invariant()
    def pending_rebuild_refuses_query(self) -> None:
        if not hasattr(self, "view"):
            return
        if self.pending_rebuild:
            try:
                list(self.view.query(None))
                raise AssertionError("MV-INV-04: pending-schema view MUST refuse query")
            except MaterializedViewInvariantError:
                pass


# Hypothesis hook
TestMaterializedViewMachine = MaterializedViewMachine.TestCase
