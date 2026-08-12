"""Protocol for OutputGuardrail — generated from OutputGuardrail.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Sequence

@runtime_checkable
class OutputVerdict(Protocol):
    """OutputGuardrail primitive — post-inference verdicts on LLM output."""

    ...

@runtime_checkable
class OutputGuardrail(Protocol):
    """OutputGuardrail primitive — post-inference verdicts on LLM output."""

    def evaluate(self, output: str, schema_ref: str | None) -> OutputVerdict: ...
