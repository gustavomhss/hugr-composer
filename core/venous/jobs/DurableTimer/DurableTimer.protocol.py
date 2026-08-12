"""Protocol for DurableTimer — generated from DurableTimer.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class TimerService(Protocol):
    """DurableTimer primitive — workflow-scoped persistent sleep."""

    async def start(self, timer: DurableTimer) -> None: ...
    async def cancel(self, workflow_id: str, timer_id: str) -> None: ...
