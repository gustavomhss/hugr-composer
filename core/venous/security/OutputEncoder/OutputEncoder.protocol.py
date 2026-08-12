"""Protocol for OutputEncoder — generated from OutputEncoder.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class OutputEncoder(Protocol):
    """OutputEncoder primitive — context-aware sink encoder for untrusted values."""

    def encode(self, value: str, sink: Sink) -> str: ...
