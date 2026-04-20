"""Hypothesis state-machine exploration of ChangeDataCapture lifecycle.

Explores random interleavings of begin_tx / stage / commit / rollback /
subscribe / checkpoint / evolve_schema. Asserts global invariants:

- CDC-INV-01: committed log positions are strictly monotonic and unique.
- CDC-INV-02: checkpoint is non-decreasing.
- CDC-INV-03: no uncommitted event surfaces via subscribe().
- CDC-INV-04: any row event in the log carries a schema_version ≤ the most
  recent schema event's version.
"""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from ChangeDataCapture import (
    ChangeDataCaptureInvariantError,
    InMemoryChangeDataCapture,
)


class ChangeDataCaptureMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.cdc = InMemoryChangeDataCapture()
        self.cdc.register_table("t", ["id"])
        self.open_txids: set[str] = set()
        self.terminal_txids: set[str] = set()
        self.next_txid = 0

    def _new_txid(self) -> str:
        tid = f"tx{self.next_txid}"
        self.next_txid += 1
        return tid

    @rule()
    def begin(self) -> None:
        if not hasattr(self, "cdc"):
            return
        tid = self._new_txid()
        self.cdc.begin_tx(tid)
        self.open_txids.add(tid)

    @rule(key=st.integers(min_value=0, max_value=100))
    def stage(self, key: int) -> None:
        if not hasattr(self, "cdc") or not self.open_txids:
            return
        tid = next(iter(self.open_txids))
        self.cdc.stage_change(tid, "t", "insert", key, None, {"id": key})

    @rule()
    def commit(self) -> None:
        if not hasattr(self, "cdc") or not self.open_txids:
            return
        tid = self.open_txids.pop()
        self.cdc.commit_tx(tid)
        self.terminal_txids.add(tid)

    @rule()
    def rollback(self) -> None:
        if not hasattr(self, "cdc") or not self.open_txids:
            return
        tid = self.open_txids.pop()
        self.cdc.rollback_tx(tid)
        self.terminal_txids.add(tid)

    @rule()
    def subscribe_read(self) -> None:
        if not hasattr(self, "cdc"):
            return
        events = list(self.cdc.subscribe("t", 0))
        for ev in events:
            assert ev.get("committed", False), "CDC-INV-03: uncommitted event leaked"

    @rule(bump=st.integers(min_value=0, max_value=3))
    def checkpoint_advance(self, bump: int) -> None:
        if not hasattr(self, "cdc"):
            return
        cur = self.cdc.checkpoint_of()
        self.cdc.checkpoint(cur + bump)

    @rule()
    def checkpoint_rewind_attempt(self) -> None:
        if not hasattr(self, "cdc"):
            return
        cur = self.cdc.checkpoint_of()
        if cur == 0:
            return
        try:
            self.cdc.checkpoint(cur - 1)
            raise AssertionError("CDC-INV-02: checkpoint rewind should be rejected")
        except ChangeDataCaptureInvariantError:
            pass

    @rule()
    def evolve(self) -> None:
        if not hasattr(self, "cdc"):
            return
        self.cdc.evolve_schema("t", ["id", "extra"])

    # --- global invariants --------------------------------------------------
    @invariant()
    def positions_strictly_monotonic(self) -> None:
        if not hasattr(self, "cdc"):
            return
        log = self.cdc.log_snapshot()
        positions = [int(e["pos"]) for e in log]  # type: ignore[arg-type]
        assert positions == sorted(positions)
        assert len(set(positions)) == len(positions)

    @invariant()
    def no_uncommitted_in_log(self) -> None:
        if not hasattr(self, "cdc"):
            return
        for ev in self.cdc.log_snapshot():
            assert ev.get("committed", False), "CDC-INV-03 violated: uncommitted on log"

    @invariant()
    def schema_precedes_row_events(self) -> None:
        if not hasattr(self, "cdc"):
            return
        current_v = 0
        for ev in self.cdc.log_snapshot():
            if ev["op"] == "schema":
                v = int(ev["schema_version"])  # type: ignore[arg-type]
                assert v >= current_v
                current_v = v
            else:
                assert int(ev["schema_version"]) <= current_v  # type: ignore[arg-type]
                assert current_v >= 1


# Hypothesis hook
TestChangeDataCaptureMachine = ChangeDataCaptureMachine.TestCase
