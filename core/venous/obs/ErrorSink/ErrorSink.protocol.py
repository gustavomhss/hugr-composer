"""Protocol for ErrorSink — generated from ErrorSink.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable

@runtime_checkable
class ErrorSink(Protocol):
    """ErrorSink primitive — captures uncaught exceptions with deterministic fingerprint."""

    def capture_exception(self, exc: BaseException) -> str: ...
    def capture_message(self, message: str) -> str: ...
    def register_fingerprinter(self, fn: Callable[[BaseException], list[str]]) -> None: ...
    def before_send(self, fn: Callable[[dict[str, object]], dict[str, object] | None]) -> None: ...
