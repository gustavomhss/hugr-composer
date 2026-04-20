"""HeterogeneousWorkerPool — Protocol-only declaration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

R = TypeVar("R")
WorkerKind = Literal["cpu", "gpu"]


@dataclass
class Task(Generic[R]):
    payload: object
    session_id: str | None = None


@runtime_checkable
class HeterogeneousWorkerPool(Protocol[R]):
    def register(
        self,
        worker_id: str,
        capabilities: frozenset[str],
        kind: WorkerKind,
        executor: Callable[[Task[object]], Awaitable[R]],
    ) -> None: ...
    def submit(self, task: Task[R], family: str) -> "asyncio.Future[R]": ...
    def on_result(
        self, worker_id: str, latency_ms: float, ok: bool
    ) -> None: ...
