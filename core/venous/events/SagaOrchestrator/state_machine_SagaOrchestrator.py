"""Hypothesis state-machine exploration of the SagaOrchestrator lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from SagaOrchestrator import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_PENDING,
    STATE_RUNNING,
    InMemorySagaOrchestrator,
    SagaDefinition,
    SagaOrchestratorInvariantError,
)

_TERMINAL = {STATE_COMPLETED, STATE_FAILED}


def _build_definition(trace: list[str]) -> SagaDefinition:
    sd = SagaDefinition("h")
    sd.register("s1", compensator=lambda p: trace.append(f"~s1:{p!r}"))(lambda p: p)
    sd.register("s2", compensator=lambda p: trace.append(f"~s2:{p!r}"))(lambda p: p)
    sd.register("s3", compensator=lambda p: trace.append(f"~s3:{p!r}"))(lambda p: p)
    return sd


class SagaMachine(RuleBasedStateMachine):
    @initialize()
    def _init(self) -> None:
        self.trace: list[str] = []
        self.saga = InMemorySagaOrchestrator(_build_definition(self.trace))
        self.cid = "m"
        self.started = False
        self.expected_completed: list[str] = []
        self.step_names = ["s1", "s2", "s3"]

    @rule()
    def op_start(self) -> None:
        self.saga.start(self.cid, {"v": 0})
        self.started = True

    @rule(step_tag=st.integers(min_value=0, max_value=2), fail=st.booleans())
    def op_step(self, step_tag: int, fail: bool) -> None:
        if not self.started:
            return
        state, _done = self.saga.status(self.cid)
        if state in _TERMINAL:
            # Terminal sagas ignore step reports — call must not raise.
            self.saga.step(self.cid, self.step_names[step_tag], 1)
            return
        next_index = len(self.expected_completed)
        if next_index >= len(self.step_names):
            return
        name = self.step_names[next_index]
        if step_tag != next_index:
            # Out-of-order report is rejected.
            try:
                self.saga.step(self.cid, self.step_names[step_tag], 1)
            except SagaOrchestratorInvariantError:
                return
            return
        if fail:
            self.saga.step(self.cid, name, {"__saga_failed__": True, "reason": "x"})
            self.expected_completed = []  # all compensated on failure of a later step
        else:
            self.saga.step(self.cid, name, {"v": next_index})
            self.expected_completed.append(name)

    @invariant()
    def state_always_known(self) -> None:
        if not hasattr(self, "saga"):
            return
        if not self.started:
            return
        state, _done = self.saga.status(self.cid)
        assert state in {STATE_PENDING, STATE_RUNNING, "compensating", STATE_COMPLETED, STATE_FAILED}

    @invariant()
    def done_is_a_prefix_of_declared_steps(self) -> None:
        if not hasattr(self, "saga") or not self.started:
            return
        _state, done = self.saga.status(self.cid)
        done_list = list(done)
        # `done` must always be a prefix of the declared step sequence.
        assert done_list == self.step_names[: len(done_list)]

    @invariant()
    def journal_length_monotonic(self) -> None:
        if not hasattr(self, "saga") or not self.started:
            return
        journal = self.saga.journal_for(self.cid)
        seqs = [r.seq for r in journal]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)


TestSagaMachine = SagaMachine.TestCase
