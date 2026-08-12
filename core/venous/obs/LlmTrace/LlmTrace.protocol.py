"""Protocol for LlmTrace — generated from LlmTrace.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping
from contextlib import AbstractContextManager

@runtime_checkable
class LlmSpan(Protocol):
    """LlmTrace primitive — OpenTelemetry GenAI SemConv 1.27+ aligned span factory."""

    def set_usage(self, input_tokens: int, output_tokens: int) -> None: ...
    def set_finish_reason(self, reason: str) -> None: ...
    def record_error(self, code: str, message: str) -> None: ...

@runtime_checkable
class LlmTrace(Protocol):
    """LlmTrace primitive — OpenTelemetry GenAI SemConv 1.27+ aligned span factory."""

    def start(self, operation: str, model_handle: str, prompt_fingerprint: str) -> AbstractContextManager[LlmSpan]: ...
