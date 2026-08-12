"""Protocol for InputGuardrail — generated from InputGuardrail.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class GuardDecision(Protocol):
    """InputGuardrail primitive — pre-model validator chain (NeMo / Guardrails AI shape)."""

    ...

@runtime_checkable
class InputGuardrail(Protocol):
    """InputGuardrail primitive — pre-model validator chain (NeMo / Guardrails AI shape)."""

    def evaluate(self, text: str, context: dict[str, str]) -> GuardDecision: ...
