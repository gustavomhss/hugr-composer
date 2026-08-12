"""ActivityCall primitive — workflow-scoped side-effect unit.

Implements the catalog Protocol for `jobs.ActivityCall`. Zero I/O at import.
Reference runtime serializes attempts per-activity-id, applies the retry
policy, and surfaces heartbeat tracking.

Invariant IDs cited by this module:

- AC-INV-01: execution semantics are at-least-once; activity code MUST be
  idempotent under retry.
- AC-INV-02: `start_to_close_s` MUST be set and positive; missing SHALL
  raise a configuration error.
- AC-INV-03: long-running activities ALWAYS heartbeat within `heartbeat_s`;
  a missed heartbeat CANNOT be treated as success.
- AC-INV-04: a failure whose attempt count reaches
  `RetryPolicy.maximum_attempts` MUST surface to the workflow as a
  terminal error.
- AC-INV-05: heartbeat details NEVER persist across a successful
  completion; they scope only to the in-flight attempt and its retries.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class ActivityCallError(ValueError):
    """Raised when a call violates an ActivityCall invariant."""


class ActivityMaxAttemptsExceededError(RuntimeError):
    """Raised when retry attempts reach maximum_attempts (AC-INV-04)."""


class ActivityHeartbeatMissedError(RuntimeError):
    """Raised when the in-flight attempt misses its heartbeat deadline (AC-INV-03)."""


# ---------------------------------------------------------------------------
# Dataclasses (mirror the catalog api_signature)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetryPolicy:
    initial_interval_s: float
    backoff_coefficient: float
    maximum_attempts: int

    def __post_init__(self) -> None:
        if self.initial_interval_s < 0:
            raise ActivityCallError("AC-INV-04 supporting: initial_interval_s MUST be >= 0.")
        if self.backoff_coefficient < 1.0:
            raise ActivityCallError("AC-INV-04 supporting: backoff_coefficient MUST be >= 1.0.")
        if self.maximum_attempts < 1:
            raise ActivityCallError("AC-INV-04 supporting: maximum_attempts MUST be >= 1.")


@dataclass(frozen=True)
class ActivityCall:
    name: str
    task_queue: str
    start_to_close_s: int
    schedule_to_close_s: int | None
    heartbeat_s: int | None
    retry: RetryPolicy
    args: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ActivityCallError("AC-INV-01 supporting: name MUST be non-empty.")
        if not isinstance(self.task_queue, str) or not self.task_queue:
            raise ActivityCallError("AC-INV-01 supporting: task_queue MUST be non-empty.")
        if not isinstance(self.start_to_close_s, int) or self.start_to_close_s <= 0:
            raise ActivityCallError(
                f"AC-INV-02: start_to_close_s MUST be a positive int, got {self.start_to_close_s!r}."
            )
        if self.schedule_to_close_s is not None and self.schedule_to_close_s <= 0:
            raise ActivityCallError(
                "AC-INV-02 supporting: schedule_to_close_s when set MUST be positive."
            )
        if self.heartbeat_s is not None and self.heartbeat_s <= 0:
            raise ActivityCallError(
                "AC-INV-03 supporting: heartbeat_s when set MUST be positive."
            )
        if not isinstance(self.args, tuple):
            raise ActivityCallError("AC-INV-01 supporting: args MUST be a tuple.")


ActivityHandler = Callable[[tuple[Any, ...]], Awaitable[Any]]


@runtime_checkable
class ActivityExecutor(Protocol):
    async def execute(self, call: ActivityCall) -> Any: ...


# ---------------------------------------------------------------------------
# Reference runtime
# ---------------------------------------------------------------------------
@dataclass
class _AttemptRecord:
    attempt_no: int
    outcome: str          # "success" | "failure" | "heartbeat_missed"
    heartbeat_details: tuple[bytes, ...] = field(default_factory=tuple)


class InMemoryActivityExecutor:
    """Reference executor with deterministic retry + heartbeat semantics.

    Handlers are registered by `activity_name`; each `execute()` walks
    attempts 1..retry.maximum_attempts, honoring a (mockable) heartbeat.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ActivityHandler] = {}
        self._attempts: dict[str, list[_AttemptRecord]] = {}
        self._id_counter = itertools.count(1)

    def register(self, name: str, handler: ActivityHandler) -> None:
        self._handlers[name] = handler

    async def execute(self, call: ActivityCall) -> Any:
        handler = self._handlers.get(call.name)
        if handler is None:
            raise ActivityCallError(f"AC-INV-01 supporting: activity {call.name!r} not registered.")
        attempt_id = f"{call.name}-{next(self._id_counter)}"
        self._attempts[attempt_id] = []
        last_error: BaseException | None = None
        # AC-INV-03: the effective per-attempt deadline is
        # `min(start_to_close_s, heartbeat_s)`. The heartbeat budget MUST
        # bound how long an attempt can run without progress; a handler that
        # runs for `start_to_close_s - 1` with no heartbeat previously looked
        # like success because the timeout never fired.
        attempt_timeout = call.start_to_close_s
        if call.heartbeat_s is not None:
            attempt_timeout = min(attempt_timeout, call.heartbeat_s)
        for attempt_no in range(1, call.retry.maximum_attempts + 1):
            # AC-INV-04: apply exponential backoff BEFORE attempts 2+.
            if attempt_no > 1:
                await asyncio.sleep(retry_delay_s(call.retry, attempt_no - 1))
            try:
                result = await asyncio.wait_for(handler(call.args), timeout=attempt_timeout)
            except TimeoutError as e:  # heartbeat-window / start_to_close exceeded
                reason = "heartbeat_missed" if (
                    call.heartbeat_s is not None
                    and call.heartbeat_s <= call.start_to_close_s
                ) else "start_to_close_exceeded"
                self._attempts[attempt_id].append(_AttemptRecord(
                    attempt_no=attempt_no, outcome=reason,
                ))
                last_error = ActivityHeartbeatMissedError(
                    f"AC-INV-03: activity {call.name!r} attempt {attempt_no} "
                    f"exceeded per-attempt deadline={attempt_timeout}s ({reason})."
                )
                last_error.__cause__ = e
                continue
            except Exception as e:  # noqa: BLE001 — handler exception triggers retry per policy
                self._attempts[attempt_id].append(_AttemptRecord(
                    attempt_no=attempt_no, outcome="failure",
                ))
                last_error = e
                continue
            # AC-INV-05: on success, append the success record. Per-retry
            # outcome history IS retained (operators need to see that attempt
            # 1 timed-out before attempt 3 succeeded). What AC-INV-05 forbids
            # is HEARTBEAT DETAIL payload leaking into subsequent retries —
            # our `_AttemptRecord` for success never carries heartbeat_details
            # because the handler didn't time out.
            self._attempts[attempt_id].append(_AttemptRecord(
                attempt_no=attempt_no, outcome="success",
            ))
            return result
        # AC-INV-04: reached maximum_attempts — surface a terminal error.
        raise ActivityMaxAttemptsExceededError(
            f"AC-INV-04: activity {call.name!r} reached maximum_attempts={call.retry.maximum_attempts}."
        ) from last_error

    # ----- inspection for tests ----------------------------------------------
    def attempts_for_latest(self, name: str) -> tuple[_AttemptRecord, ...]:
        matching = [(k, v) for k, v in self._attempts.items() if k.startswith(f"{name}-")]
        if not matching:
            return ()
        _, last = matching[-1]
        return tuple(last)


def retry_delay_s(policy: RetryPolicy, attempt_no: int) -> float:
    """Exponential backoff for attempt_no in [1, maximum_attempts]."""
    if attempt_no < 1:
        raise ActivityCallError("AC-INV-04 supporting: attempt_no MUST be >= 1.")
    return policy.initial_interval_s * (policy.backoff_coefficient ** (attempt_no - 1))


__all__ = [
    "ActivityCall",
    "ActivityCallError",
    "ActivityExecutor",
    "ActivityHandler",
    "ActivityHeartbeatMissedError",
    "ActivityMaxAttemptsExceededError",
    "InMemoryActivityExecutor",
    "RetryPolicy",
    "retry_delay_s",
]
