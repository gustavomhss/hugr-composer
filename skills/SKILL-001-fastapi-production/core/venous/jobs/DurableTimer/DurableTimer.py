"""DurableTimer primitive — workflow-scoped persistent sleep.

Implements the catalog Protocol for `jobs.DurableTimer`. Zero I/O at import.
Reference runtime records every timer in an event log and fires a
once-only event; cancel races are resolved by ordering cancel BEFORE fire.

Invariant IDs cited by this module:

- DT-INV-01: a fired timer MUST be recorded as an event so workflow replay
  reconstructs the same fire point.
- DT-INV-02: wall-clock sleep calls inside a workflow are FORBIDDEN; the
  DurableTimer surface is the only sleep API.
- DT-INV-03: a canceled timer SHALL NEVER fire; cancellation ALWAYS reaches
  the workflow before a fired event is recorded.
- DT-INV-04: `delay_s` MUST be non-negative; a negative delay CANNOT be
  scheduled and raises an argument error.
- DT-INV-05: a single worker NEVER caps the number of concurrent durable
  timers at the process level because timers persist server-side.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, runtime_checkable

MIN_DELAY_S: Final[float] = 0.0


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class DurableTimerError(ValueError):
    """Raised when a call violates a DurableTimer invariant."""


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------
class TimerStatus(Enum):
    SCHEDULED = "scheduled"
    FIRED = "fired"
    CANCELED = "canceled"


@dataclass(frozen=True)
class DurableTimer:
    workflow_id: str
    timer_id: str
    delay_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.workflow_id, str) or not self.workflow_id:
            raise DurableTimerError("DT-INV-04 supporting: workflow_id MUST be non-empty.")
        if not isinstance(self.timer_id, str) or not self.timer_id:
            raise DurableTimerError("DT-INV-04 supporting: timer_id MUST be non-empty.")
        if not isinstance(self.delay_s, (int, float)):
            raise DurableTimerError(
                f"DT-INV-04: delay_s MUST be numeric, got {type(self.delay_s).__name__}."
            )
        if self.delay_s < MIN_DELAY_S:
            raise DurableTimerError(
                f"DT-INV-04: delay_s MUST be >= {MIN_DELAY_S}, got {self.delay_s}."
            )


@runtime_checkable
class TimerService(Protocol):
    async def start(self, timer: DurableTimer) -> None: ...
    async def cancel(self, workflow_id: str, timer_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Reference runtime
# ---------------------------------------------------------------------------
@dataclass
class _TimerRecord:
    timer: DurableTimer
    status: TimerStatus
    fire_event_seq: int | None = None   # monotonic seq of the fire event, if fired


class InMemoryTimerService:
    """Reference TimerService.

    - Every transition (schedule / cancel / fire) is recorded as an event
      in a workflow-scoped event log (DT-INV-01).
    - Cancel is idempotent-safe; firing a canceled timer is FORBIDDEN
      (DT-INV-03).
    - No per-worker cap on concurrent scheduled timers (DT-INV-05) — the
      runtime stores them in an unbounded dict (in real deployments, the
      Temporal server persists them durably).
    """

    def __init__(self) -> None:
        self._timers: dict[tuple[str, str], _TimerRecord] = {}
        self._events: list[tuple[str, str, str, int]] = []  # (wf, tid, kind, seq)
        self._seq: int = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def start(self, timer: DurableTimer) -> None:
        key = (timer.workflow_id, timer.timer_id)
        if key in self._timers:
            # DT-INV-01: a (workflow_id, timer_id) pair is allocated at most
            # once over its lifetime. Re-scheduling after SCHEDULED, FIRED,
            # or CANCELED is FORBIDDEN — fire-at-most-once follows from this.
            raise DurableTimerError(
                f"DT-INV-01 supporting: timer {key} already exists with status "
                f"{self._timers[key].status.value}; duplicate schedule FORBIDDEN."
            )
        self._timers[key] = _TimerRecord(timer=timer, status=TimerStatus.SCHEDULED)
        self._events.append((timer.workflow_id, timer.timer_id, "scheduled", self._next_seq()))

    async def cancel(self, workflow_id: str, timer_id: str) -> None:
        key = (workflow_id, timer_id)
        rec = self._timers.get(key)
        if rec is None:
            raise DurableTimerError(f"DT-INV-03 supporting: no timer {key} to cancel.")
        if rec.status is TimerStatus.FIRED:
            raise DurableTimerError(
                f"DT-INV-03: timer {key} already FIRED; CANNOT cancel."
            )
        if rec.status is TimerStatus.CANCELED:
            return  # idempotent
        rec.status = TimerStatus.CANCELED
        self._events.append((workflow_id, timer_id, "canceled", self._next_seq()))

    # ----- simulated server-side fire -------------------------------------
    def fire(self, workflow_id: str, timer_id: str) -> None:
        """DT-INV-01/03: fire only if SCHEDULED; record a fired event."""
        key = (workflow_id, timer_id)
        rec = self._timers.get(key)
        if rec is None:
            raise DurableTimerError(f"DT-INV-01 supporting: no timer {key} to fire.")
        if rec.status is TimerStatus.CANCELED:
            raise DurableTimerError(
                f"DT-INV-03: timer {key} canceled; fire FORBIDDEN."
            )
        if rec.status is TimerStatus.FIRED:
            raise DurableTimerError(
                f"DT-INV-01: timer {key} already fired; SHALL NOT fire twice."
            )
        seq = self._next_seq()
        rec.status = TimerStatus.FIRED
        rec.fire_event_seq = seq
        self._events.append((workflow_id, timer_id, "fired", seq))

    # ----- inspection for tests -------------------------------------------
    def status_of(self, workflow_id: str, timer_id: str) -> TimerStatus:
        rec = self._timers.get((workflow_id, timer_id))
        if rec is None:
            raise DurableTimerError(f"no timer {(workflow_id, timer_id)}.")
        return rec.status

    def event_log(self, workflow_id: str) -> tuple[tuple[str, str, str, int], ...]:
        return tuple(e for e in self._events if e[0] == workflow_id)


# ---------------------------------------------------------------------------
# Adapter that exposes ONLY DurableTimer — wall-clock sleep NOT exposed.
# ---------------------------------------------------------------------------
async def wait_for_timer(
    service: TimerService, timer: DurableTimer,
    *, poll_s: float = 0.01, max_wait_s: float = 5.0,
) -> None:
    """Polling adapter: await until the reference service marks the timer FIRED.

    DT-INV-02: this is the ONLY sleep surface available to workflow code;
    there is no `time.sleep` exposed by the primitive.
    """
    await service.start(timer)
    elapsed = 0.0
    if not isinstance(service, InMemoryTimerService):
        raise DurableTimerError("wait_for_timer needs a TimerService with observable status (reference runtime).")
    while elapsed < max_wait_s:
        if service.status_of(timer.workflow_id, timer.timer_id) is not TimerStatus.SCHEDULED:
            return
        await asyncio.sleep(poll_s)
        elapsed += poll_s
    # DT-INV-02: distinguish "timer fired" (early return above) from
    # "wait budget exhausted". The previous implementation fell through
    # silently, giving callers no signal that the timer was abandoned —
    # a subtle bug when composed with workflow step orchestration.
    current = service.status_of(timer.workflow_id, timer.timer_id)
    raise asyncio.TimeoutError(
        f"DT-INV-02: wait_for_timer exhausted max_wait_s={max_wait_s}s without "
        f"timer {timer.timer_id!r} leaving SCHEDULED (status={current.name})."
    )


__all__ = [
    "MIN_DELAY_S",
    "DurableTimer",
    "DurableTimerError",
    "InMemoryTimerService",
    "TimerService",
    "TimerStatus",
    "wait_for_timer",
]
