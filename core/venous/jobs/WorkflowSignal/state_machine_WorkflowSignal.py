"""Hypothesis RuleBasedStateMachine for WorkflowSignal."""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from WorkflowSignal import (
    InMemorySignalSender,
    WorkflowNotFoundError,
    WorkflowSignal,
    WorkflowSignalError,
)


_WFS = ["w-a", "w-b"]


class SignalStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.sender = InMemorySignalSender()
        self.opened: set[str] = set()
        self.closed: set[str] = set()
        self.signals_sent: dict[str, int] = {w: 0 for w in _WFS}

    @rule(wf=st.sampled_from(_WFS))
    def try_open(self, wf: str) -> None:
        if wf not in self.opened:
            self.sender.register_open(wf, "T", "q")
            self.opened.add(wf)

    @rule(wf=st.sampled_from(_WFS))
    def try_close(self, wf: str) -> None:
        if wf in self.opened and wf not in self.closed:
            self.sender.close(wf)
            self.closed.add(wf)

    @rule(wf=st.sampled_from(_WFS),
          name=st.sampled_from(["a", "b", "c"]))
    def try_send(self, wf: str, name: str) -> None:
        try:
            asyncio.run(self.sender.send(WorkflowSignal(workflow_id=wf, name=name, payload=None)))
            self.signals_sent[wf] += 1
        except (WorkflowNotFoundError, WorkflowSignalError):
            return

    @invariant()
    def closed_never_accepts(self) -> None:
        # WFS-INV-03: closed workflows never gain new signals.
        for wf in self.closed:
            # Record a snapshot; verify no NEW signal appended since close
            # by attempting another send — MUST raise.
            try:
                asyncio.run(self.sender.send(WorkflowSignal(workflow_id=wf, name="probe", payload=None)))
                raise AssertionError(f"WFS-INV-03 violated for {wf}")
            except WorkflowNotFoundError:
                pass

    @invariant()
    def history_length_matches_sent(self) -> None:
        for wf in self.opened:
            hist = self.sender.history_of(wf)
            signals = [e for e in hist if e[1] == "signal"]
            assert len(signals) == self.signals_sent[wf]


TestSignalStateMachine = SignalStateMachine.TestCase
