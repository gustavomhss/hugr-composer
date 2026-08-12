"""Protocol for SamplingPolicy — generated from SamplingPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class SamplingPolicy(Protocol):
    """SamplingPolicy primitive — head-based sampling decisions."""

    def should_sample(self) -> SamplingDecision: ...
    def description(self) -> str: ...
