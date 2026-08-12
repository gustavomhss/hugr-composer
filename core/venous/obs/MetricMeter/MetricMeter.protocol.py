"""Protocol for MetricMeter — generated from MetricMeter.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Mapping, Sequence

@runtime_checkable
class Counter(Protocol):
    """MetricMeter primitive — OpenTelemetry-aligned instrument factory."""

    def add(self, value: float, attributes: Mapping[str, str] | None) -> None: ...

@runtime_checkable
class UpDownCounter(Protocol):
    """MetricMeter primitive — OpenTelemetry-aligned instrument factory."""

    def add(self, value: float, attributes: Mapping[str, str] | None) -> None: ...

@runtime_checkable
class Histogram(Protocol):
    """MetricMeter primitive — OpenTelemetry-aligned instrument factory."""

    def record(self, value: float, attributes: Mapping[str, str] | None) -> None: ...

@runtime_checkable
class MetricMeter(Protocol):
    """MetricMeter primitive — OpenTelemetry-aligned instrument factory."""

    def counter(self, name: str) -> Counter: ...
    def up_down_counter(self, name: str) -> UpDownCounter: ...
    def histogram(self, name: str) -> Histogram: ...
    def observable_gauge(self, name: str, callback: Callable[[], float]) -> None: ...
