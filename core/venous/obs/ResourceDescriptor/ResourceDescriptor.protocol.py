"""Protocol for ResourceDescriptor — generated from ResourceDescriptor.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class ResourceDescriptorProtocol(Protocol):
    """Immutable descriptor of a telemetry-emitting entity."""

    def merged_with(self, overrides: Mapping[str, str]) -> ResourceDescriptor: ...
    def to_attributes(self) -> Mapping[str, str]: ...
