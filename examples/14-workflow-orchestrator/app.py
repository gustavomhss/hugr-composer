"""Durable workflow orchestrator — replay, retry, compensate, singleton."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ActivityCall:
    name: str
    forward: Callable[[], None]
    compensate: Callable[[], None]


@dataclass
class WorkflowRun:
    id: str
    completed_steps: list[str] = field(default_factory=list)
    compensated_steps: list[str] = field(default_factory=list)
    status: str = "running"   # running | completed | compensated | timed_out
    idempotency_seen: set[str] = field(default_factory=set)


class WorkflowAlreadyRunningError(Exception):
    pass


class WorkflowStore:
    """Persistent store of `WorkflowRun` records + a one-instance-per-id lock."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def acquire(self, workflow_id: str) -> WorkflowRun:
        with self._lock:
            if workflow_id in self._running:
                raise WorkflowAlreadyRunningError(workflow_id)
            self._running.add(workflow_id)
            run = self._runs.setdefault(workflow_id, WorkflowRun(id=workflow_id))
            return run

    def release(self, workflow_id: str) -> None:
        with self._lock:
            self._running.discard(workflow_id)

    def get(self, workflow_id: str) -> WorkflowRun | None:
        with self._lock:
            return self._runs.get(workflow_id)


class SagaOrchestrator:
    """Runs activities in order; on timeout, compensates in reverse."""

    def __init__(self, store: WorkflowStore) -> None:
        self._store = store

    def run(
        self, workflow_id: str, steps: list[ActivityCall],
        *, timeout_at_step: int | None = None,
        crash_at_step: int | None = None,
    ) -> WorkflowRun:
        """Execute `steps` against the persisted run.

        Skips steps whose name is already in `completed_steps` (resume).
        If ``timeout_at_step`` (1-indexed) is set, that step "times out"
        and compensations fire in reverse.
        If ``crash_at_step`` is set, the orchestrator raises mid-run
        without marking the step complete — caller can re-invoke to resume.
        """
        run = self._store.acquire(workflow_id)
        try:
            for i, step in enumerate(steps, start=1):
                if step.name in run.completed_steps:
                    continue  # already done in a previous run
                if timeout_at_step == i:
                    run.status = "timed_out"
                    # Compensate in reverse.
                    for done in reversed(run.completed_steps):
                        for s in steps:
                            if s.name == done:
                                s.compensate()
                                run.compensated_steps.append(done)
                                break
                    run.status = "compensated"
                    return run
                if crash_at_step == i:
                    raise RuntimeError(f"simulated crash at step {i}")
                step.forward()
                run.completed_steps.append(step.name)
            run.status = "completed"
            return run
        finally:
            self._store.release(workflow_id)

    def idempotent_call(
        self, workflow_id: str, key: str, fn: Callable[[], None],
    ) -> bool:
        """Execute fn() unless `key` was already applied. Returns True on apply."""
        run = self._store.get(workflow_id)
        if run is None:
            run = self._store._runs.setdefault(workflow_id, WorkflowRun(id=workflow_id))
        if key in run.idempotency_seen:
            return False
        fn()
        run.idempotency_seen.add(key)
        return True
