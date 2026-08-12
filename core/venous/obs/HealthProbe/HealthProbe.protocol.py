"""Protocol for HealthProbe — generated from HealthProbe.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class HealthProbe(Protocol):
    """Canonical Protocol — see COLLISIONS_RESOLVED.md §1."""

    async def liveness(self) -> HealthReport: ...
    async def readiness(self) -> HealthReport: ...
    def register_dependency(self, name: str, probe: HealthProbe) -> None: ...
