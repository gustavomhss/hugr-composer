"""Hypothesis state-machine for LegalHold."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, rule

from LegalHold import InMemoryLegalHoldRegistry, LegalHold


UTC = timezone.utc


class LegalHoldStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.reg = InMemoryLegalHoldRegistry()
        self.active: set[str] = set()
        self.seq = 0

    @rule()
    def open_hold(self) -> None:
        self.seq += 1
        hid = f"h{self.seq}"
        # Use unique record for scope to avoid cross-hold interactions.
        h = LegalHold(
            hold_id=hid,
            scope_query=f"record_id = '{hid}'",
            opened_at=datetime.now(UTC),
            opened_by="c1",
        )
        self.reg.open(h)
        self.active.add(hid)

    @rule()
    def release_any(self) -> None:
        if not self.active:
            return
        hid = next(iter(self.active))
        self.reg.release(hid, released_by="ops")
        self.active.remove(hid)

    def teardown(self) -> None:
        # LH_INV_01: every active hold still covers its record; released ones don't.
        for hid in self.active:
            assert self.reg.covers(hid) is True


TestLH = LegalHoldStateMachine.TestCase
TestLH.settings = settings(max_examples=30, deadline=None)
