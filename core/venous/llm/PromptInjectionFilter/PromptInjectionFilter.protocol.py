"""Protocol for PromptInjectionFilter — generated from PromptInjectionFilter.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Iterable, Iterator

@runtime_checkable
class QuarantinedText(Protocol):
    """PromptInjectionFilter primitive — quarantine untrusted text for LLM context."""

    ...

@runtime_checkable
class PromptInjectionFilter(Protocol):
    """PromptInjectionFilter primitive — quarantine untrusted text for LLM context."""

    def quarantine(self, raw: str, kind: str) -> QuarantinedText: ...

@runtime_checkable
class StrippingRule(Protocol):
    """A composable detection/redaction rule."""

    def match(self, text: str, kind: str) -> Iterable[tuple[int, int]]: ...
