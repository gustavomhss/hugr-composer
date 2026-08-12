"""Protocol for RouterPipeline — generated from RouterPipeline.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable, Mapping, Sequence

@runtime_checkable
class RouterPipeline(Protocol):
    """Protocol for the RouterPipeline primitive."""

    def attach(self, route: str) -> None: ...
