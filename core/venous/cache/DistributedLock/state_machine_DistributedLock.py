"""Hypothesis state-machine exploration for DistributedLock.

Models: two owners, one resource, a fake clock. Invariants:
- DL_INV_01: at most one holder at any instant.
- DL_INV_03: unlock by non-holder is rejected.
"""

from __future__ import annotations

import asyncio

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from hypothesis.strategies import integers, sampled_from

from DistributedLock import (
    FakeClock,
    InMemoryDistributedLock,
    LockHandle,
    LockOwnershipError,
)


def _run(coro):  # type: ignore[no-untyped-def]  # test helper
    return asyncio.run(coro)


OWNERS = ("o1", "o2", "o3")


class DistributedLockMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.clock = FakeClock()
        self.lock = InMemoryDistributedLock(clock=self.clock)
        self.current_handle: LockHandle | None = None
        self.current_owner: str | None = None

    @rule(owner=sampled_from(OWNERS), lease=integers(min_value=1, max_value=60))
    def acquire(self, owner: str, lease: int) -> None:
        async def op() -> None:
            h = await self.lock.try_lock("r", owner, lease)
            if h is not None:
                self.current_handle = h
                self.current_owner = owner
        _run(op())

    @rule(unlocker=sampled_from(OWNERS))
    @precondition(lambda self: self.current_handle is not None)
    def release(self, unlocker: str) -> None:
        async def op() -> None:
            assert self.current_handle is not None
            if unlocker == self.current_owner:
                await self.lock.unlock(self.current_handle)
                self.current_handle = None
                self.current_owner = None
            else:
                # Foreign unlock MUST raise LockOwnershipError per DL_INV_03.
                try:
                    await self.lock.unlock(
                        LockHandle(resource_id="r", owner_id=unlocker, lease_s=1),
                    )
                except LockOwnershipError:
                    pass
                else:
                    msg = "DL_INV_03: foreign unlock should have raised."
                    raise AssertionError(msg)
        _run(op())

    @rule(dt=integers(min_value=0, max_value=120))
    def tick(self, dt: int) -> None:
        self.clock.advance(float(dt))
        # If lease has expired, forget the handle (the primitive also reclaims
        # on the next acquire).
        if self.current_handle is not None and not self.lock.is_held("r"):
            self.current_handle = None
            self.current_owner = None

    @invariant()
    def single_holder(self) -> None:
        # At most one owner is currently active.
        holder = self.lock.current_holder("r")
        if self.current_handle is not None and holder is not None:
            assert holder == self.current_owner


TestDistributedLockStateMachine = DistributedLockMachine.TestCase
TestDistributedLockStateMachine.settings = settings(max_examples=50, stateful_step_count=30)
