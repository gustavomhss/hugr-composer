"""VirtualActor primitive — location-transparent single-writer actor contract.

Implements the catalog Protocol for `extras.VirtualActor`. The module performs
zero I/O at import. The reference implementation simulates single-writer
semantics via an asyncio lock per ActorId.

Invariant IDs cited by this module:

- VACT-INV-01: only one invocation of a given ActorId runs at a time;
  concurrent calls MUST queue in arrival order.
- VACT-INV-02: actor state NEVER escapes the actor instance; callers ALWAYS
  read it through invoke, never via direct store access.
- VACT-INV-03: reminders MUST survive actor deactivation and restart; they
  SHALL fire after the configured period regardless of host.
- VACT-INV-04: timers within an actor CANNOT outlive deactivation; reminders
  are the durable option.
- VACT-INV-05: caller code MUST NOT depend on the physical host of an actor
  because placement can migrate on failover.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_REMINDER_PERIOD_S: Final[int] = 1


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------
class VirtualActorError(ValueError):
    """Raised when a call violates a VirtualActor invariant."""


# ---------------------------------------------------------------------------
# Dataclasses (mirror the catalog api_signature)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ActorId:
    actor_type: str
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.actor_type, str) or not self.actor_type:
            raise VirtualActorError("VACT-INV-05 supporting: actor_type MUST be a non-empty string.")
        if not isinstance(self.key, str) or not self.key:
            raise VirtualActorError("VACT-INV-05 supporting: key MUST be a non-empty string.")


@runtime_checkable
class VirtualActor(Protocol):
    async def invoke(self, id: ActorId, method: str, payload: bytes) -> bytes: ...  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
    async def set_reminder(self, id: ActorId, name: str, period_s: int, ttl_s: int | None = None) -> None: ...  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
    async def cancel_reminder(self, id: ActorId, name: str) -> None: ...  # noqa: A002 — VACT-INV-05 catalog signature uses `id`


MethodHandler = Callable[[bytes], Awaitable[bytes]]


@dataclass
class _ActorInstance:
    """Per-ActorId runtime state: single-writer lock + method table.

    `_ActorInstance` is an internal reference-impl detail. Callers MUST NOT
    import it — VACT-INV-02 forbids direct state access outside invoke.
    """

    actor_id: ActorId
    handlers: dict[str, MethodHandler]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    invocations: int = 0


# ---------------------------------------------------------------------------
# Reference runtime
# ---------------------------------------------------------------------------
class InMemoryVirtualActor:
    """Reference runtime: one asyncio.Lock per ActorId (VACT-INV-01).

    Reminders are persisted in-memory; real deployments back this with a
    store that survives process restart.
    """

    def __init__(self) -> None:
        self._instances: dict[ActorId, _ActorInstance] = {}
        self._reminders: dict[tuple[ActorId, str], dict[str, int | None]] = {}
        self._cancelled_reminders: set[tuple[ActorId, str]] = set()

    def register(
        self,
        actor_type: str,
        key: str,
        handlers: dict[str, MethodHandler],
    ) -> None:
        """Register a method table for a concrete ActorId. Applications
        typically call this once per actor type; tests call it per key.
        """
        aid = ActorId(actor_type=actor_type, key=key)
        if aid in self._instances:
            # VACT-INV-01 supporting: re-registering an already-live actor is
            # forbidden because the existing lock would be dropped.
            raise VirtualActorError(
                f"VACT-INV-01 supporting: actor {aid} already registered."
            )
        self._instances[aid] = _ActorInstance(actor_id=aid, handlers=dict(handlers))

    async def invoke(self, id: ActorId, method: str, payload: bytes) -> bytes:  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
        if id not in self._instances:
            raise VirtualActorError(f"VACT-INV-02: actor {id} is not activated.")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise VirtualActorError(
                f"VACT-INV-02 supporting: payload MUST be bytes, got {type(payload).__name__}."
            )
        inst = self._instances[id]
        handler = inst.handlers.get(method)
        if handler is None:
            raise VirtualActorError(
                f"VACT-INV-02 supporting: method {method!r} not found on {id.actor_type!r}."
            )
        # VACT-INV-01: serialize per ActorId.
        async with inst.lock:
            inst.invocations += 1
            result = await handler(bytes(payload))
        if not isinstance(result, (bytes, bytearray, memoryview)):
            raise VirtualActorError(
                f"VACT-INV-02: handler returned non-bytes {type(result).__name__}."
            )
        return bytes(result)

    async def set_reminder(
        self,
        id: ActorId,  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
        name: str,
        period_s: int,
        ttl_s: int | None = None,
    ) -> None:
        """VACT-INV-03: reminders persist across deactivation (here: across
        process lifetime of the runtime; a real impl persists to a store)."""
        if period_s < MIN_REMINDER_PERIOD_S:
            raise VirtualActorError(
                f"VACT-INV-03: period_s MUST be >= {MIN_REMINDER_PERIOD_S}, got {period_s}."
            )
        if ttl_s is not None and ttl_s <= 0:
            raise VirtualActorError(
                f"VACT-INV-03 supporting: ttl_s when set MUST be > 0, got {ttl_s}."
            )
        key = (id, name)
        self._reminders[key] = {"period_s": period_s, "ttl_s": ttl_s}
        self._cancelled_reminders.discard(key)

    async def cancel_reminder(self, id: ActorId, name: str) -> None:  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
        key = (id, name)
        if key not in self._reminders:
            raise VirtualActorError(
                f"VACT-INV-03 supporting: reminder {name!r} on {id} does not exist."
            )
        self._reminders.pop(key)
        self._cancelled_reminders.add(key)

    # ----- inspection hooks used by tests -------------------------------------
    def reminder_count(self) -> int:
        return len(self._reminders)

    def has_reminder(self, id: ActorId, name: str) -> bool:  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
        return (id, name) in self._reminders

    def invocations_for(self, id: ActorId) -> int:  # noqa: A002 — VACT-INV-05 catalog signature uses `id`
        inst = self._instances.get(id)
        return inst.invocations if inst is not None else 0

    def deactivate_all(self) -> None:
        """VACT-INV-04: simulated deactivation — in-process timers would be
        dropped; reminders persist and survive. Used by tests to prove the rule.
        """
        self._instances.clear()

    def reinstate(
        self,
        actor_type: str,
        key: str,
        handlers: dict[str, MethodHandler],
    ) -> None:
        """Reinstate an actor on a (simulated) new host (VACT-INV-05).

        VACT-INV-01: refuse to reinstate over a LIVE actor. Replacing the
        existing `_ActorInstance` would swap the per-actor `asyncio.Lock`
        mid-flight, allowing a second invoker to acquire the fresh lock
        while the original invocation is still holding the old one — two
        concurrent writers for the same `ActorId`. Caller MUST `deactivate`
        / `deactivate_all` before reinstating a running actor.
        """
        aid = ActorId(actor_type=actor_type, key=key)
        if aid in self._instances:
            raise VirtualActorError(
                f"VACT-INV-01: refusing to reinstate over live actor {aid!r}; "
                "call deactivate_all() first or target a previously-deactivated key."
            )
        self._instances[aid] = _ActorInstance(actor_id=aid, handlers=dict(handlers))


__all__ = [
    "MIN_REMINDER_PERIOD_S",
    "ActorId",
    "InMemoryVirtualActor",
    "MethodHandler",
    "VirtualActor",
    "VirtualActorError",
]
