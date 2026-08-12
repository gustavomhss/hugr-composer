"""Protocol for ChangeDataCapture — generated from ChangeDataCapture.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable, Iterator, Mapping

@runtime_checkable
class ChangeDataCapture(Protocol):
    """ChangeDataCapture primitive — Kleppmann DDIA / Richardson CDC section."""

    def subscribe(self, table: str, from_position: object) -> Iterator[Any]: ...
    def checkpoint(self, position: object) -> None: ...
    def schema(self, table: str) -> dict[str, object]: ...
