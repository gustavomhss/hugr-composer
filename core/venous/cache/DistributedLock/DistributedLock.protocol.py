"""Protocol for DistributedLock — generated from DistributedLock.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from DistributedLock import LockHandle

@runtime_checkable
class DistributedLock(Protocol):
    """DistributedLock primitive — named mutex with lease expiry and owner fencing."""

    async def try_lock(self, resource_id: str, owner_id: str, lease_s: int) -> LockHandle | None: ...
    async def unlock(self, handle: LockHandle) -> None: ...

@runtime_checkable
class ClockProtocol(Protocol):
    """DistributedLock primitive — named mutex with lease expiry and owner fencing."""

    def now(self) -> float: ...
