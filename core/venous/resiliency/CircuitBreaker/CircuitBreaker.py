"""CircuitBreaker primitive — three-state stability guard for a failing dependency.

States: ``closed`` (normal), ``open`` (short-circuit), ``half_open`` (probing).
Transitions are metric-driven: a rolling window of outcomes determines when the
breaker opens; a monotonic cooldown determines when it probes; a single probe
failure slams it back to open.

Invariant IDs cited here (full text in ``CircuitBreaker.md``):

- CBREAK_INV_01: when state is open, calls MUST be rejected without invoking
  the wrapped function.
- CBREAK_INV_02: open → half_open SHALL occur only after the cooldown interval
  has elapsed on a monotonic clock.
- CBREAK_INV_03: half_open MUST permit at most ``permitted_calls_in_half_open``
  probes concurrently.
- CBREAK_INV_04: a single failure recorded while half_open SHALL force the
  state back to open and restart the cooldown.
- CBREAK_INV_05: state transition decisions CANNOT use a sample smaller than
  ``minimum_number_of_calls``.
- CBREAK_INV_06: the breaker NEVER mutates state without emitting a
  ``state_transition`` event on the observability bus.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Final, Literal, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

State = Literal["closed", "open", "half_open"]
STATES: Final[frozenset[str]] = frozenset({"closed", "open", "half_open"})


class CircuitBreakerError(RuntimeError):
    """Raised when an invariant is violated or the breaker rejects a call."""


class CircuitOpenError(CircuitBreakerError):
    """Raised when the breaker rejects a call because state is open (CBREAK_INV_01)."""


class HalfOpenRejectedError(CircuitBreakerError):
    """Raised when half_open has no remaining probe permits (CBREAK_INV_03)."""


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature)
# ---------------------------------------------------------------------------
@runtime_checkable
class CircuitBreaker(Protocol):
    name: str
    state: State

    async def call(
        self, fn: Callable[..., Awaitable[T]], /, *args: object, **kwargs: object
    ) -> T: ...
    def on_success(self, elapsed_ms: float) -> None: ...
    def on_failure(self, exc: BaseException, elapsed_ms: float) -> None: ...
    def force_open(self, reason: str) -> None: ...
    def allow_probe(self) -> bool: ...


# ---------------------------------------------------------------------------
# Observability bus — minimal for in-module use
# ---------------------------------------------------------------------------
class TransitionEvent:
    """One observable state transition. Emitted on every mutation (CBREAK_INV_06)."""

    __slots__ = ("from_state", "monotonic_ns", "reason", "to_state")

    def __init__(
        self, from_state: State, to_state: State, reason: str, monotonic_ns: int
    ) -> None:
        self.from_state: State = from_state
        self.to_state: State = to_state
        self.reason: str = reason
        self.monotonic_ns: int = monotonic_ns


# ---------------------------------------------------------------------------
# Reference in-memory implementation
# ---------------------------------------------------------------------------
class InMemoryCircuitBreaker:
    """Reference implementation; real deployments swap for resilience4j-style adapter.

    Thread-safe. A single internal lock guards state + counters. The underlying
    sliding window is count-based; the Protocol is unchanged if a time-based
    variant is registered later.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_rate_threshold: float = 0.5,
        minimum_number_of_calls: int = 5,
        cooldown_ms: int = 1_000,
        permitted_calls_in_half_open: int = 1,
        window_size: int = 10,
    ) -> None:
        if minimum_number_of_calls < 1:
            raise CircuitBreakerError(
                "CBREAK_INV_05: minimum_number_of_calls MUST be >= 1."
            )
        if permitted_calls_in_half_open < 1:
            raise CircuitBreakerError(
                "CBREAK_INV_03: permitted_calls_in_half_open MUST be >= 1."
            )
        if not 0.0 < failure_rate_threshold <= 1.0:
            raise CircuitBreakerError(
                "failure_rate_threshold MUST be in (0.0, 1.0]."
            )
        if window_size < minimum_number_of_calls:
            raise CircuitBreakerError(
                "window_size MUST be >= minimum_number_of_calls."
            )
        self.name: str = name
        self.state: State = "closed"
        self._failure_rate_threshold: float = failure_rate_threshold
        self._minimum_number_of_calls: int = minimum_number_of_calls
        self._cooldown_ms: int = cooldown_ms
        self._permitted_calls_in_half_open: int = permitted_calls_in_half_open
        self._window_size: int = window_size
        self._window: deque[bool] = deque(maxlen=window_size)
        self._opened_at_ns: int | None = None
        self._probes_in_flight: int = 0
        self._lock = threading.RLock()
        self._events: list[TransitionEvent] = []

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    @property
    def events(self) -> tuple[TransitionEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _emit(self, from_state: State, to_state: State, reason: str) -> None:
        """CBREAK_INV_06: every state mutation emits an event."""
        self._events.append(
            TransitionEvent(from_state, to_state, reason, time.monotonic_ns())
        )

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------
    def force_open(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise CircuitBreakerError(
                "force_open reason MUST be a non-empty string."
            )
        with self._lock:
            if self.state != "open":
                self._transition("open", f"force_open:{reason}")

    def allow_probe(self) -> bool:
        """Return True iff a caller may issue a probe against the wrapped dep.

        Encodes CBREAK_INV_02 (cooldown must elapse before half_open) and
        CBREAK_INV_03 (max ``permitted_calls_in_half_open`` probes concurrently).
        """
        with self._lock:
            if self.state == "closed":
                return True
            if self.state == "open":
                if self._cooldown_elapsed():
                    self._transition("half_open", "cooldown_elapsed")
                else:
                    return False
            # half_open
            if self._probes_in_flight < self._permitted_calls_in_half_open:
                self._probes_in_flight += 1
                return True
            return False

    def _cooldown_elapsed(self) -> bool:
        if self._opened_at_ns is None:
            return True
        return (time.monotonic_ns() - self._opened_at_ns) >= (
            self._cooldown_ms * 1_000_000
        )

    # ------------------------------------------------------------------
    # Outcome hooks
    # ------------------------------------------------------------------
    def on_success(self, elapsed_ms: float) -> None:
        if elapsed_ms < 0:
            raise CircuitBreakerError("elapsed_ms MUST NOT be negative.")
        with self._lock:
            self._window.append(True)
            if self.state == "half_open":
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                if self._probes_in_flight == 0:
                    self._transition("closed", "probe_succeeded")
            elif self.state == "closed":
                self._maybe_open()

    def on_failure(self, exc: BaseException, elapsed_ms: float) -> None:
        if not isinstance(exc, BaseException):
            raise CircuitBreakerError(
                "on_failure requires a BaseException instance."
            )
        if elapsed_ms < 0:
            raise CircuitBreakerError("elapsed_ms MUST NOT be negative.")
        with self._lock:
            self._window.append(False)
            if self.state == "half_open":
                # CBREAK_INV_04: one failure → back to open, cooldown restarts.
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                self._transition("open", f"half_open_failure:{type(exc).__name__}")
            elif self.state == "closed":
                self._maybe_open()

    def _maybe_open(self) -> None:
        # CBREAK_INV_05: decision requires >= minimum_number_of_calls.
        if len(self._window) < self._minimum_number_of_calls:
            return
        failures = sum(1 for ok in self._window if not ok)
        rate = failures / len(self._window)
        if rate >= self._failure_rate_threshold:
            self._transition("open", f"failure_rate:{rate:.3f}")

    def _transition(self, new_state: State, reason: str) -> None:
        if new_state not in STATES:
            raise CircuitBreakerError(
                f"invalid target state {new_state!r}; MUST be one of {sorted(STATES)}."
            )
        old = self.state
        self.state = new_state
        if new_state == "open":
            self._opened_at_ns = time.monotonic_ns()
            self._probes_in_flight = 0
        elif new_state == "closed":
            self._opened_at_ns = None
            self._probes_in_flight = 0
            self._window.clear()
        elif new_state == "half_open":
            self._probes_in_flight = 0
        self._emit(old, new_state, reason)

    # ------------------------------------------------------------------
    # Call wrapper
    # ------------------------------------------------------------------
    async def call(
        self, fn: Callable[..., Awaitable[T]], /, *args: object, **kwargs: object
    ) -> T:
        if not self.allow_probe():
            # CBREAK_INV_01: open → reject without invoking fn.
            if self.state == "open":
                raise CircuitOpenError(
                    f"CBREAK_INV_01: breaker {self.name!r} is open; call rejected."
                )
            raise HalfOpenRejectedError(
                f"CBREAK_INV_03: breaker {self.name!r} has no probe permits."
            )
        started = time.monotonic()
        try:
            result: T = await fn(*args, **kwargs)
        except BaseException as exc:  # CBREAK_INV_04: classify every exception path
            self.on_failure(exc, (time.monotonic() - started) * 1000.0)
            raise
        self.on_success((time.monotonic() - started) * 1000.0)
        return result


__all__ = [
    "STATES",
    "CircuitBreaker",
    "CircuitBreakerError",
    "CircuitOpenError",
    "HalfOpenRejectedError",
    "InMemoryCircuitBreaker",
    "State",
    "TransitionEvent",
]
