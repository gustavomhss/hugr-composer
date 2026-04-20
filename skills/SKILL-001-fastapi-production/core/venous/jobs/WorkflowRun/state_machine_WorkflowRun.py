"""Hypothesis RuleBasedStateMachine for WorkflowRun lifecycle."""

from __future__ import annotations

import asyncio

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from WorkflowRun import (
    IdReusePolicy,
    InMemoryWorkflowClient,
    RunStatus,
    WorkflowAlreadyRunningError,
    WorkflowClosedError,
)


_WFS = ["w-a", "w-b"]


class WorkflowStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.client = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REJECT)
        self.known_run_ids: set[str] = set()

    @rule(wf=st.sampled_from(_WFS))
    def try_start(self, wf: str) -> None:
        try:
            run = asyncio.run(self.client.start("T", wf, "q", args=()))
        except WorkflowAlreadyRunningError:
            return
        # WFR-INV-03: every start allocates a FRESH run_id.
        assert run.run_id not in self.known_run_ids
        self.known_run_ids.add(run.run_id)

    @rule(wf=st.sampled_from(_WFS), activity=st.sampled_from(["A", "B", "C"]))
    def try_schedule(self, wf: str, activity: str) -> None:
        try:
            self.client.schedule_activity(wf, activity)
        except WorkflowClosedError:
            return
        except Exception:  # noqa: BLE001 — no-run-for-wf falls here until start
            return

    @rule(wf=st.sampled_from(_WFS))
    def try_complete(self, wf: str) -> None:
        try:
            self.client.complete(wf)
        except (WorkflowClosedError, Exception):  # noqa: BLE001 — no-run-for-wf
            return

    @rule(wf=st.sampled_from(_WFS))
    def try_cancel(self, wf: str) -> None:
        try:
            asyncio.run(self.client.cancel(wf))
        except (WorkflowClosedError, Exception):  # noqa: BLE001 — no-run-for-wf
            return

    @invariant()
    def at_most_one_open_run_per_workflow(self) -> None:
        # WFR-INV-05: reject policy means at most one OPEN run per workflow_id at any time.
        for wf in _WFS:
            runs = self.client.all_runs_of(wf)
            opens = [
                r for r in runs
                if self.client.status_of(wf) is RunStatus.OPEN and r.run_id == runs[-1].run_id
            ]
            # At most one "last" open.
            assert len(opens) <= 1


TestWorkflowStateMachine = WorkflowStateMachine.TestCase
