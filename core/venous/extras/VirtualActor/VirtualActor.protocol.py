"""Protocol for VirtualActor — generated from VirtualActor.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class VirtualActor(Protocol):
    """VirtualActor primitive — location-transparent single-writer actor contract."""

    async def invoke(self, id: ActorId, method: str, payload: bytes) -> bytes: ...
    async def set_reminder(self, id: ActorId, name: str, period_s: int, ttl_s: int | None) -> None: ...
    async def cancel_reminder(self, id: ActorId, name: str) -> None: ...
