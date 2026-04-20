"""WorkflowRun primitive — durable replayable orchestration identity.

Implements the catalog Protocol for `jobs.WorkflowRun`. Zero I/O at import.
The reference implementation maintains an in-memory history of workflow
events and enforces run-id uniqueness per workflow_id.

Invariant IDs cited by this module:

- WFR-INV-01: workflow code MUST be deterministic so replay from the event
  history reconstructs the same decisions.
- WFR-INV-02: non-deterministic calls (random, wall-clock, direct network IO)
  inside a workflow function are FORBIDDEN.
- WFR-INV-03: a completed or canceled WorkflowRun CANNOT be resumed under
  the same run_id; reruns ALWAYS allocate a new run_id.
- WFR-INV-04: every externally observable effect MUST flow through an
  activity, timer, signal, or child workflow.
- WFR-INV-05: starting a workflow with an id that already has an open run
  SHALL either reject or reuse according to the configured id-reuse policy.
"""

from __future__ import annotations

import itertools
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORKFLOW_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./]{0,99}$")


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class WorkflowRunError(ValueError):
    """Raised when a call violates a WorkflowRun invariant."""


class WorkflowAlreadyRunningError(RuntimeError):
    """Raised when id-reuse policy REJECT sees an existing open run (WFR-INV-05)."""


class WorkflowClosedError(RuntimeError):
    """Raised when an operation targets a closed run (WFR-INV-03)."""


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------
class RunStatus(Enum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


class IdReusePolicy(Enum):
    REJECT = "reject"                 # WFR-INV-05: refuse if an open run exists
    REUSE_EXISTING = "reuse_existing" # return the existing open run
    TERMINATE_EXISTING = "terminate_existing"  # close the existing run then start anew


@dataclass(frozen=True)
class WorkflowRun:
    workflow_id: str
    run_id: str
    task_queue: str


# ---------------------------------------------------------------------------
# Protocol (mirrors the catalog api_signature)
# ---------------------------------------------------------------------------
@runtime_checkable
class WorkflowClient(Protocol):
    async def start(
        self,
        workflow_type: str,
        workflow_id: str,
        task_queue: str,
        args: tuple[Any, ...],
    ) -> WorkflowRun: ...
    async def describe(self, workflow_id: str) -> WorkflowRun: ...
    async def cancel(self, workflow_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Event history (internal)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkflowEvent:
    event_id: int
    kind: str                 # "started" | "activity_scheduled" | "timer_fired" | "signaled" | "completed" | "canceled"
    attributes: tuple[tuple[str, str], ...] = ()


@dataclass
class _RunState:
    run: WorkflowRun
    workflow_type: str
    status: RunStatus = RunStatus.OPEN
    history: list[WorkflowEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def validate_workflow_id(workflow_id: str) -> None:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise WorkflowRunError(
            f"WFR-INV-01 supporting: workflow_id MUST match {WORKFLOW_ID_RE.pattern}, got {workflow_id!r}."
        )


def validate_task_queue(task_queue: str) -> None:
    if not isinstance(task_queue, str) or not task_queue:
        raise WorkflowRunError(
            "WFR-INV-04 supporting: task_queue MUST be a non-empty string."
        )


# ---------------------------------------------------------------------------
# Reference runtime
# ---------------------------------------------------------------------------
class InMemoryWorkflowClient:
    """Reference `WorkflowClient` implementation.

    Designed for tests. Tracks one map `workflow_id -> _RunState` plus a
    per-workflow run-history index. Determinism is enforced by rejecting
    APIs that would introduce wall-clock or random inputs into the workflow
    surface (see absence of `time.time`-style methods).
    """

    def __init__(self, *, id_reuse: IdReusePolicy = IdReusePolicy.REJECT) -> None:
        self._runs: dict[str, _RunState] = {}
        self._history_index: dict[str, list[_RunState]] = {}
        self._event_counter = itertools.count(1)
        self._run_counter = itertools.count(1)
        self._id_reuse = id_reuse
        # WFR-INV-05: guard every mutation / check-then-set path so concurrent
        # `start` calls under REJECT policy cannot both observe `existing is
        # None` and create duplicate runs for the same workflow_id.
        self._mu = threading.Lock()

    # ----- catalog API -------------------------------------------------------
    async def start(
        self,
        workflow_type: str,
        workflow_id: str,
        task_queue: str,
        args: tuple[Any, ...],
    ) -> WorkflowRun:
        if not isinstance(workflow_type, str) or not workflow_type:
            raise WorkflowRunError("WFR-INV-01 supporting: workflow_type MUST be non-empty.")
        validate_workflow_id(workflow_id)
        validate_task_queue(task_queue)
        if not isinstance(args, tuple):
            raise WorkflowRunError("WFR-INV-01 supporting: args MUST be a tuple (deterministic payload).")

        with self._mu:
            existing = self._runs.get(workflow_id)
            if existing is not None and existing.status is RunStatus.OPEN:
                if self._id_reuse is IdReusePolicy.REJECT:
                    raise WorkflowAlreadyRunningError(
                        f"WFR-INV-05: workflow {workflow_id!r} already has an open run "
                        f"{existing.run.run_id!r} (policy=REJECT)."
                    )
                if self._id_reuse is IdReusePolicy.REUSE_EXISTING:
                    return existing.run
                if self._id_reuse is IdReusePolicy.TERMINATE_EXISTING:
                    existing.status = RunStatus.CANCELED
                    existing.history.append(WorkflowEvent(
                        event_id=next(self._event_counter), kind="canceled",
                    ))

            run_id = f"run-{next(self._run_counter)}"
            run = WorkflowRun(workflow_id=workflow_id, run_id=run_id, task_queue=task_queue)
            state = _RunState(run=run, workflow_type=workflow_type)
            state.history.append(WorkflowEvent(
                event_id=next(self._event_counter), kind="started",
                attributes=(("workflow_type", workflow_type), ("task_queue", task_queue)),
            ))
            self._runs[workflow_id] = state
            self._history_index.setdefault(workflow_id, []).append(state)
            return run

    async def describe(self, workflow_id: str) -> WorkflowRun:
        with self._mu:
            state = self._runs.get(workflow_id)
            if state is None:
                raise WorkflowRunError(f"WFR-INV-05 supporting: no run for {workflow_id!r}.")
            return state.run

    async def cancel(self, workflow_id: str) -> None:
        with self._mu:
            state = self._runs.get(workflow_id)
            if state is None:
                raise WorkflowRunError(f"WFR-INV-03 supporting: no run to cancel for {workflow_id!r}.")
            if state.status is not RunStatus.OPEN:
                raise WorkflowClosedError(
                    f"WFR-INV-03: run {state.run.run_id!r} already {state.status.value}; cannot cancel."
                )
            state.status = RunStatus.CANCELED
            state.history.append(WorkflowEvent(
                event_id=next(self._event_counter), kind="canceled",
            ))

    # ----- operations allowed on open runs (each becomes an event) -----------
    def schedule_activity(self, workflow_id: str, activity_name: str) -> None:
        """WFR-INV-04: externally observable effects go through activity events."""
        with self._mu:
            state = self._open_state(workflow_id)
            state.history.append(WorkflowEvent(
                event_id=next(self._event_counter), kind="activity_scheduled",
                attributes=(("name", activity_name),),
            ))

    def complete(self, workflow_id: str) -> None:
        with self._mu:
            state = self._open_state(workflow_id)
            state.status = RunStatus.COMPLETED
            state.history.append(WorkflowEvent(
                event_id=next(self._event_counter), kind="completed",
            ))

    def fail(self, workflow_id: str, reason: str) -> None:
        with self._mu:
            state = self._open_state(workflow_id)
            state.status = RunStatus.FAILED
            state.history.append(WorkflowEvent(
                event_id=next(self._event_counter), kind="failed",
                attributes=(("reason", reason),),
            ))

    # ----- inspection for tests ----------------------------------------------
    def status_of(self, workflow_id: str) -> RunStatus:
        with self._mu:
            state = self._runs.get(workflow_id)
            if state is None:
                raise WorkflowRunError(f"no run for {workflow_id!r}.")
            return state.status

    def history_of(self, workflow_id: str) -> tuple[WorkflowEvent, ...]:
        with self._mu:
            state = self._runs.get(workflow_id)
            return tuple(state.history) if state is not None else ()

    def all_runs_of(self, workflow_id: str) -> tuple[WorkflowRun, ...]:
        with self._mu:
            return tuple(s.run for s in self._history_index.get(workflow_id, ()))

    def replay(self, workflow_id: str) -> tuple[str, ...]:
        """WFR-INV-01: returns the recorded kinds of a run's history.

        This surfaces the stored sequence verbatim — it does NOT re-execute a
        workflow function against the history. Genuine replay-determinism
        enforcement (re-running user code and asserting identical decisions)
        requires a host runtime (Temporal, DBOS) and is explicitly out of scope
        for the reference primitive.
        """
        with self._mu:
            state = self._runs.get(workflow_id)
            if state is None:
                return ()
            return tuple(ev.kind for ev in state.history)

    def _open_state(self, workflow_id: str) -> _RunState:
        state = self._runs.get(workflow_id)
        if state is None:
            raise WorkflowRunError(f"no run for {workflow_id!r}.")
        if state.status is not RunStatus.OPEN:
            raise WorkflowClosedError(
                f"WFR-INV-03: run {state.run.run_id!r} is {state.status.value}; operations FORBIDDEN on closed runs."
            )
        return state


__all__ = [
    "WORKFLOW_ID_RE",
    "IdReusePolicy",
    "InMemoryWorkflowClient",
    "RunStatus",
    "WorkflowAlreadyRunningError",
    "WorkflowClient",
    "WorkflowClosedError",
    "WorkflowEvent",
    "WorkflowRun",
    "WorkflowRunError",
    "validate_task_queue",
    "validate_workflow_id",
]
