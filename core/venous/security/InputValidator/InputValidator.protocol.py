"""Protocol for InputValidator — generated from InputValidator.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable, Sequence

@runtime_checkable
class InputValidator(Protocol):
    """InputValidator primitive — schema-first ingress parser."""

    def parse(self, raw: object, schema: type[T]) -> T: ...
