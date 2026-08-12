"""Protocol for DataResidencyPolicy — generated from DataResidencyPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuditSink(Protocol):
    """DataResidencyPolicy primitive — per-class allowed regions + transfer mechanism."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class ResidencyEnforcer(Protocol):
    """Catalog-defined Protocol."""

    def bind(self, policy: DataResidencyPolicy) -> None: ...
    def check_write(self, data_class: str, region: str) -> None: ...
    def check_transfer(self, data_class: str, source: str, destination: str) -> None: ...
