"""WorkflowSignal primitive — asynchronous fire-and-forget write to an open run.

Implements the catalog Protocol for `jobs.WorkflowSignal`. Zero I/O at import.
Reference runtime appends signal events into a workflow-scoped event log and
refuses delivery to closed runs.

Invariant IDs cited by this module:

- WFS-INV-01: a signal MUST be recorded as an event in the workflow history
  before it is considered delivered.
- WFS-INV-02: the sender CANNOT observe a return value from the signal;
  any response shape SHALL use an update or query instead.
- WFS-INV-03: signals to a workflow that has closed MUST be rejected with a
  not-found style error; signals NEVER start a closed run.
- WFS-INV-04: `send_with_start` ALWAYS atomically starts a new run or
  targets the existing open run under the same workflow id.
- WFS-INV-05: handler code for a signal MUST follow the same determinism
  rules as the workflow itself.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

MAX_PAYLOAD_BYTES: Final[int] = 64 * 1024  # 64 KiB heuristic cap


class SignalDeliveryStatus(Enum):
    DELIVERED = "delivered"
    REJECTED_CLOSED = "rejected_closed"
    REJECTED_UNKNOWN = "rejected_unknown"


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class WorkflowSignalError(ValueError):
    """Raised when a call violates a WorkflowSignal invariant."""


class WorkflowNotFoundError(LookupError):
    """Raised when send targets a workflow that does not exist or is closed (WFS-INV-03)."""


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkflowSignal:
    workflow_id: str
    name: str
    payload: Any

    def __post_init__(self) -> None:
        if not isinstance(self.workflow_id, str) or not self.workflow_id:
            raise WorkflowSignalError("WFS-INV-01 supporting: workflow_id MUST be non-empty.")
        if not isinstance(self.name, str) or not self.name:
            raise WorkflowSignalError("WFS-INV-01 supporting: signal name MUST be non-empty.")


@runtime_checkable
class SignalSender(Protocol):
    async def send(self, signal: WorkflowSignal) -> None: ...
    async def send_with_start(
        self,
        signal: WorkflowSignal,
        workflow_type: str,
        task_queue: str,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Reference runtime
# ---------------------------------------------------------------------------
@dataclass
class _WfState:
    workflow_id: str
    run_id: str
    workflow_type: str
    task_queue: str
    status: str   # "open" | "closed"
    history: list[tuple[int, str, str]]  # (seq, kind, name)


class InMemorySignalSender:
    """Reference `SignalSender` implementation.

    Signals are recorded BEFORE they are considered delivered (WFS-INV-01).
    Closed workflows reject sends with `WorkflowNotFoundError` (WFS-INV-03).
    `send_with_start` atomically reuses the open run or allocates a new one
    under the same workflow_id (WFS-INV-04).
    """

    def __init__(self) -> None:
        self._runs: dict[str, _WfState] = {}
        self._seq = itertools.count(1)
        self._run_counter = itertools.count(1)

    # ----- management (not part of the catalog surface) ----------------------
    def register_open(self, workflow_id: str, workflow_type: str, task_queue: str) -> str:
        run_id = f"run-{next(self._run_counter)}"
        self._runs[workflow_id] = _WfState(
            workflow_id=workflow_id, run_id=run_id,
            workflow_type=workflow_type, task_queue=task_queue,
            status="open", history=[],
        )
        return run_id

    def close(self, workflow_id: str) -> None:
        state = self._runs.get(workflow_id)
        if state is None:
            raise WorkflowNotFoundError(f"no run for {workflow_id!r}.")
        state.status = "closed"

    # ----- catalog API -------------------------------------------------------
    async def send(self, signal: WorkflowSignal) -> None:
        self._validate_payload(signal.payload)
        state = self._runs.get(signal.workflow_id)
        if state is None:
            raise WorkflowNotFoundError(
                f"WFS-INV-03: workflow {signal.workflow_id!r} does not exist; signals NEVER start a closed run."
            )
        if state.status != "open":
            raise WorkflowNotFoundError(
                f"WFS-INV-03: workflow {signal.workflow_id!r} is closed; signal rejected."
            )
        state.history.append((next(self._seq), "signal", signal.name))

    async def send_with_start(
        self,
        signal: WorkflowSignal,
        workflow_type: str,
        task_queue: str,
    ) -> str:
        self._validate_payload(signal.payload)
        if not isinstance(workflow_type, str) or not workflow_type:
            raise WorkflowSignalError("WFS-INV-04 supporting: workflow_type MUST be non-empty.")
        if not isinstance(task_queue, str) or not task_queue:
            raise WorkflowSignalError("WFS-INV-04 supporting: task_queue MUST be non-empty.")
        state = self._runs.get(signal.workflow_id)
        if state is not None and state.status == "open":
            # WFS-INV-04: atomically target existing open run.
            state.history.append((next(self._seq), "signal", signal.name))
            return state.run_id
        # WFS-INV-04: atomically start a fresh run AND record the signal.
        run_id = self.register_open(signal.workflow_id, workflow_type, task_queue)
        target = self._runs[signal.workflow_id]
        target.history.append((next(self._seq), "started", workflow_type))
        target.history.append((next(self._seq), "signal", signal.name))
        return run_id

    # ----- inspection for tests ---------------------------------------------
    def history_of(self, workflow_id: str) -> tuple[tuple[int, str, str], ...]:
        state = self._runs.get(workflow_id)
        return tuple(state.history) if state is not None else ()

    def status_of(self, workflow_id: str) -> str:
        state = self._runs.get(workflow_id)
        if state is None:
            raise WorkflowNotFoundError(f"no run for {workflow_id!r}.")
        return state.status

    @staticmethod
    def _validate_payload(payload: object) -> None:
        if payload is None:
            return  # None is a valid "no payload".
        # WFS-INV-05: payload MUST be serialisable through a deterministic
        # encoder — bytes-like or primitive scalar or small dict/list.
        if isinstance(payload, (bytes, bytearray, memoryview)):
            if len(bytes(payload)) > MAX_PAYLOAD_BYTES:
                raise WorkflowSignalError(
                    f"WFS-INV-01 supporting: payload > {MAX_PAYLOAD_BYTES} bytes FORBIDDEN."
                )
            return
        if isinstance(payload, (str, int, float, bool)):
            return
        if isinstance(payload, (list, tuple, dict)):
            return
        raise WorkflowSignalError(
            f"WFS-INV-05: payload type {type(payload).__name__} is not serialisable; FORBIDDEN."
        )


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "InMemorySignalSender",
    "SignalDeliveryStatus",
    "SignalSender",
    "WorkflowNotFoundError",
    "WorkflowSignal",
    "WorkflowSignalError",
]
