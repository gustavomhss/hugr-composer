"""Protocol for PromptTemplate — generated from PromptTemplate.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class PromptTemplate(Protocol):
    """PromptTemplate primitive — versioned, pinned, parameterized prompts."""

    def render(self, values: Mapping[str, str]) -> str: ...
    def fingerprint(self) -> str: ...
