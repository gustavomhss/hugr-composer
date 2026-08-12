"""Protocol for Tracer — generated from Tracer.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager

@runtime_checkable
class Span(Protocol):
    """Tracer primitive — OpenTelemetry-aligned span factory with W3C Trace Context."""

    def set_attribute(self, key: str, value: str | float | bool) -> None: ...
    def add_event(self, name: str, attributes: Mapping[str, object] | None) -> None: ...
    def record_exception(self, exc: BaseException) -> None: ...
    def set_status(self, code: str, description: str | None) -> None: ...

@runtime_checkable
class Tracer(Protocol):
    """Tracer primitive — OpenTelemetry-aligned span factory with W3C Trace Context."""

    def start_as_current_span(self, name: str) -> AbstractContextManager[Span]: ...
    def inject(self, carrier: dict[str, str]) -> None: ...
    def extract(self, carrier: Mapping[str, str]) -> object: ...
