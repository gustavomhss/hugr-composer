"""Tests for the workflow orchestrator example."""
from __future__ import annotations

import pytest

from app import (
    ActivityCall,
    SagaOrchestrator,
    WorkflowAlreadyRunningError,
    WorkflowStore,
)


def _make_steps(effects: list[str], compensations: list[str]):
    def mkstep(name: str) -> ActivityCall:
        return ActivityCall(
            name=name,
            forward=lambda n=name: effects.append(n),
            compensate=lambda n=name: compensations.append(n),
        )
    return [mkstep(n) for n in ["step-1", "step-2", "step-3", "step-4", "step-5"]]


def test_restart_resumes_from_last_completed_step() -> None:
    store = WorkflowStore()
    orch = SagaOrchestrator(store)
    effects: list[str] = []
    steps = _make_steps(effects, [])

    # First run crashes at step 3 — only 1+2 complete.
    with pytest.raises(RuntimeError):
        orch.run("wf-1", steps, crash_at_step=3)
    assert effects == ["step-1", "step-2"]

    # Restart: steps 1+2 are skipped (already in completed_steps); 3-5 run.
    orch.run("wf-1", steps)
    assert effects == ["step-1", "step-2", "step-3", "step-4", "step-5"]
    assert store.get("wf-1").status == "completed"


def test_idempotent_activity_no_double_side_effect() -> None:
    store = WorkflowStore()
    orch = SagaOrchestrator(store)
    # Prime the run.
    store.acquire("wf-1")
    store.release("wf-1")
    fired: list[str] = []
    # First call fires; retry with same key is a no-op.
    assert orch.idempotent_call("wf-1", "charge-1", lambda: fired.append("$")) is True
    assert orch.idempotent_call("wf-1", "charge-1", lambda: fired.append("$")) is False
    assert fired == ["$"]


def test_timeout_at_step_3_compensates_2_then_1() -> None:
    store = WorkflowStore()
    orch = SagaOrchestrator(store)
    effects: list[str] = []
    comps: list[str] = []
    steps = _make_steps(effects, comps)

    run = orch.run("wf-timeout", steps, timeout_at_step=3)
    assert run.status == "compensated"
    assert effects == ["step-1", "step-2"]
    assert comps == ["step-2", "step-1"]  # reverse order


def test_two_concurrent_runs_of_same_id_rejected() -> None:
    store = WorkflowStore()
    store.acquire("wf-1")
    with pytest.raises(WorkflowAlreadyRunningError):
        store.acquire("wf-1")
    store.release("wf-1")
    # Now a new acquire is allowed.
    store.acquire("wf-1")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
