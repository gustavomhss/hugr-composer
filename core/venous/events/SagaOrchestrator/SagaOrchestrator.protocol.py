"""Protocol for SagaOrchestrator — generated from SagaOrchestrator.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Iterable

@runtime_checkable
class SagaOrchestrator(Protocol):
    """SagaOrchestrator primitive — Richardson/Garcia-Molina long-running transaction."""

    def start(self, correlation_id: str, input: Any) -> None: ...
    def step(self, correlation_id: str, name: str, outcome: Any) -> None: ...
    def compensate(self, correlation_id: str, from_step: str) -> None: ...
    def status(self, correlation_id: str) -> tuple[str, Iterable[str]]: ...
