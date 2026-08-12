"""Protocol for ActivityCall — generated from ActivityCall.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class ActivityExecutor(Protocol):
    """ActivityCall primitive — workflow-scoped side-effect unit."""

    async def execute(self, call: ActivityCall) -> Any: ...
