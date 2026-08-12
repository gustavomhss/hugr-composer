"""Protocol for MiddlewarePipeline — generated from MiddlewarePipeline.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class Middleware(Protocol):
    """A single stage in the pipeline."""

    ...

@runtime_checkable
class MiddlewarePipeline(Protocol):
    """Protocol for the MiddlewarePipeline primitive; mirrors catalog api_signature."""

    def use(self, mw: Middleware) -> MiddlewarePipeline: ...
    async def run(self, ctx: RequestContext) -> None: ...
