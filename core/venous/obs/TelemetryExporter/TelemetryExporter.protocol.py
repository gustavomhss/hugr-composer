"""Protocol for TelemetryExporter — generated from TelemetryExporter.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping, Sequence

@runtime_checkable
class TelemetryExporter(Protocol):
    """Catalog-defined Protocol surface (verbatim)."""

    def export(self, batch: Sequence[object]) -> ExportResult: ...
    def force_flush(self) -> bool: ...
    def shutdown(self) -> bool: ...
