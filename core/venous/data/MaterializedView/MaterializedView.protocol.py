"""Protocol for MaterializedView — generated from MaterializedView.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Iterable, Mapping

@runtime_checkable
class MaterializedView(Protocol):
    """MaterializedView primitive — Kleppmann DDIA / Richardson CQRS read model."""

    def name(self) -> str: ...
    def apply(self, event: Any) -> None: ...
    def rebuild(self, source: Iterable[Any]) -> None: ...
    def query(self, criteria: object) -> Iterable[Any]: ...
