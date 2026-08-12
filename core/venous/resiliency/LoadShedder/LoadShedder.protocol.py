"""Protocol for LoadShedder — generated from LoadShedder.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class LoadShedder(Protocol):
    """LoadShedder primitive — priority-aware admission control for overload regimes."""

    def admit(self, priority: Priority, queue_depth: int, cpu_load_ewma: float) -> bool: ...
    def current_cutoff(self) -> Priority: ...
    def shed_rate(self) -> float: ...
