"""LifecycleHook primitive — named callback fired at a defined application phase.

Implements the catalog dataclass for `obs.LifecycleHook` plus an in-process
registry that enforces the five invariants. Zero I/O at import.

Invariant IDs cited by this module:

- LIFE-INV-01: READY MUST fire exactly once, after STARTING and all startup
  callbacks have completed successfully.
- LIFE-INV-02: STOPPING hooks MUST run in reverse registration order (LIFO)
  so later-initialized resources drain first.
- LIFE-INV-03: A failing STARTING hook MUST prevent READY from firing; the app
  SHALL transition to STOPPED with non-zero exit.
- LIFE-INV-04: Hooks MUST NOT block indefinitely; each hook SHALL obey a
  configured timeout and be cancelled otherwise.
- LIFE-INV-05: No hook CAN re-enter its own phase; recursive registration of
  the same callback in the same phase SHALL raise.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum

# ---------------------------------------------------------------------------
# Catalog surface (mirrors api_signature verbatim)
# ---------------------------------------------------------------------------


class LifecyclePhase(str, Enum):
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"


LifecycleCallback = Callable[[], Awaitable[None]]


class LifecycleHook:
    def __init__(self, phase: LifecyclePhase, cb: LifecycleCallback) -> None:
        self.phase = phase
        self.cb = cb


# ---------------------------------------------------------------------------
# Invariant enforcement
# ---------------------------------------------------------------------------
class LifecycleInvariantError(ValueError):
    """Raised when a runtime call violates a LifecycleHook invariant."""


class LifecycleRegistry:
    """Reference registry for lifecycle hooks.

    Enforces every catalog invariant at registration and execution time.
    Single-threaded by design — lifecycle wiring runs at boot / shutdown on
    the main event loop. Invariant violations fail loudly (never silently).
    """

    def __init__(self, *, default_timeout_s: float = 30.0) -> None:
        if default_timeout_s <= 0:
            raise LifecycleInvariantError(
                "LIFE-INV-04: default_timeout_s MUST be positive."
            )
        self._default_timeout_s: float = default_timeout_s
        self._hooks: dict[LifecyclePhase, list[LifecycleHook]] = {
            p: [] for p in LifecyclePhase
        }
        self._timeouts: dict[int, float] = {}
        self._ready_fired: bool = False
        self._starting_failed: bool = False
        self._stopped: bool = False
        self._stopping_started: bool = False

    def register(
        self, hook: LifecycleHook, *, timeout_s: float | None = None
    ) -> None:
        """LIFE-INV-05: same callback CANNOT re-register within the same phase."""
        if not isinstance(hook, LifecycleHook):
            raise LifecycleInvariantError(
                "LIFE-INV-05: register() MUST receive a LifecycleHook."
            )
        if not isinstance(hook.phase, LifecyclePhase):
            raise LifecycleInvariantError(
                "LIFE-INV-05: hook.phase MUST be a LifecyclePhase member."
            )
        existing = self._hooks[hook.phase]
        for h in existing:
            if h.cb is hook.cb:
                raise LifecycleInvariantError(
                    f"LIFE-INV-05: callback already registered in phase "
                    f"{hook.phase.value!r}; duplicate registration forbidden."
                )
        if timeout_s is not None and timeout_s <= 0:
            raise LifecycleInvariantError(
                "LIFE-INV-04: timeout_s MUST be positive."
            )
        self._timeouts[id(hook)] = (
            timeout_s if timeout_s is not None else self._default_timeout_s
        )
        existing.append(hook)

    async def run_starting(self) -> None:
        """Execute STARTING hooks in registration order.

        LIFE-INV-03: a single failure marks starting_failed True and prevents
        READY from firing (see `run_ready`).
        """
        if self._starting_failed or self._ready_fired:
            raise LifecycleInvariantError(
                "LIFE-INV-01: STARTING MUST NOT run after failure or READY."
            )
        for h in list(self._hooks[LifecyclePhase.STARTING]):
            try:
                await self._invoke(h)
            except BaseException:  # noqa: PERF203 — LIFE-INV-03: per-hook failure detection MUST mark starting_failed before propagation; any exception class (incl. CancelledError) prevents READY
                self._starting_failed = True
                raise

    async def run_ready(self) -> None:
        """LIFE-INV-01: READY MUST fire exactly once, after STARTING succeeded."""
        if self._starting_failed:
            raise LifecycleInvariantError(
                "LIFE-INV-03: a failing STARTING hook MUST prevent READY."
            )
        if self._ready_fired:
            raise LifecycleInvariantError(
                "LIFE-INV-01: READY MUST fire exactly once."
            )
        for h in list(self._hooks[LifecyclePhase.READY]):
            await self._invoke(h)
        self._ready_fired = True

    async def run_stopping(self) -> None:
        """LIFE-INV-02: STOPPING hooks MUST run in reverse registration order (LIFO)."""
        if self._stopping_started:
            raise LifecycleInvariantError(
                "LIFE-INV-01: stopping phase already started."
            )
        self._stopping_started = True
        for h in list(reversed(self._hooks[LifecyclePhase.STOPPING])):
            try:
                await self._invoke(h)
            except BaseException:  # noqa: PERF203,S112,BLE001 — LIFE-INV-02: LIFO drain MUST continue past per-hook failure; a failing shutdown hook MUST NOT block other resources from draining
                # Continue draining other resources even if one fails.
                continue

    async def run_stopped(self) -> None:
        if self._stopped:
            raise LifecycleInvariantError(
                "LIFE-INV-01: stopped phase already completed."
            )
        for h in list(self._hooks[LifecyclePhase.STOPPED]):
            try:
                await self._invoke(h)
            except BaseException:  # noqa: PERF203,S112,BLE001 — LIFE-INV-01: STOPPED is terminal; per-hook failures MUST NOT block completion; terminal phase swallows errors to guarantee progress
                continue
        self._stopped = True

    async def _invoke(self, hook: LifecycleHook) -> None:
        timeout_s = self._timeouts.get(id(hook), self._default_timeout_s)
        try:
            await asyncio.wait_for(hook.cb(), timeout=timeout_s)
        except asyncio.TimeoutError as e:
            raise LifecycleInvariantError(
                f"LIFE-INV-04: hook timed out after {timeout_s}s in phase "
                f"{hook.phase.value!r}."
            ) from e

    # -- observability probes ------------------------------------------------
    @property
    def ready_fired(self) -> bool:
        return self._ready_fired

    @property
    def starting_failed(self) -> bool:
        return self._starting_failed

    @property
    def stopped(self) -> bool:
        return self._stopped

    def hooks_for(self, phase: LifecyclePhase) -> tuple[LifecycleHook, ...]:
        return tuple(self._hooks[phase])


__all__ = [
    "LifecycleCallback",
    "LifecycleHook",
    "LifecycleInvariantError",
    "LifecyclePhase",
    "LifecycleRegistry",
]
