"""Protocol for WorkflowRun — generated from WorkflowRun.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class WorkflowClient(Protocol):
    """WorkflowRun primitive — durable replayable orchestration identity."""

    async def start(self, workflow_type: str, workflow_id: str, task_queue: str, args: tuple[Any, ...]) -> WorkflowRun: ...
    async def describe(self, workflow_id: str) -> WorkflowRun: ...
    async def cancel(self, workflow_id: str) -> None: ...
