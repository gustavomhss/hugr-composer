"""Protocol for HistogramBuckets — generated from HistogramBuckets.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Sequence

@runtime_checkable
class HistogramBucketsProtocol(Protocol):
    """Immutable histogram boundaries with unit discipline."""

    def latency_ms_default(self) -> HistogramBuckets: ...
    def payload_bytes_default(self) -> HistogramBuckets: ...
