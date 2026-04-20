"""LlmTrace primitive — OpenTelemetry GenAI SemConv 1.27+ aligned span factory.

Implements the catalog Protocol for `obs.LlmTrace` and installs runtime
invariant checkers. The module performs zero I/O at import; optional
OpenTelemetry SDK integration is lazy.

Invariant IDs cited by this module:

- LLMTRACE-INV-01: every model call SHALL open exactly one LlmTrace span; a
  call-site reaching the provider without an open span is FORBIDDEN.
- LLMTRACE-INV-02: span attribute keys MUST use OpenTelemetry GenAI semantic
  conventions (`gen_ai.system`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, ...).
- LLMTRACE-INV-03: every span MUST record a non-empty `prompt_fingerprint` so
  the trace correlates with the PromptTemplate version that produced it.
- LLMTRACE-INV-04: on provider error the span MUST call `record_error` before
  exiting; swallowing the error without recording is FORBIDDEN.
- LLMTRACE-INV-05: child tool-call spans MUST nest under the model-call span
  so the causal chain is reconstructable end-to-end.

Privacy-first: prompt/response content is NEVER attached unless the caller
opts in explicitly via `capture_content=True` at tracer construction.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants — OpenTelemetry GenAI Semantic Conventions 1.27+
# ---------------------------------------------------------------------------
GEN_AI_SYSTEM: Final[str] = "gen_ai.system"
GEN_AI_REQUEST_MODEL: Final[str] = "gen_ai.request.model"
GEN_AI_REQUEST_TEMPERATURE: Final[str] = "gen_ai.request.temperature"
GEN_AI_RESPONSE_FINISH_REASONS: Final[str] = "gen_ai.response.finish_reasons"
GEN_AI_USAGE_INPUT_TOKENS: Final[str] = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final[str] = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: Final[str] = "gen_ai.usage.cache_read_input_tokens"
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: Final[str] = (
    "gen_ai.usage.cache_creation_input_tokens"
)
GEN_AI_PROMPT_FINGERPRINT: Final[str] = "gen_ai.prompt.fingerprint"
GEN_AI_OPERATION_NAME: Final[str] = "gen_ai.operation.name"

GEN_AI_REQUIRED_ATTRS: Final[frozenset[str]] = frozenset(
    {
        GEN_AI_OPERATION_NAME,
        GEN_AI_REQUEST_MODEL,
        GEN_AI_PROMPT_FINGERPRINT,
    }
)

GEN_AI_ALLOWED_PREFIX: Final[str] = "gen_ai."

FINISH_REASONS: Final[frozenset[str]] = frozenset(
    {"stop", "length", "content_filter", "tool_calls", "error"}
)

# OTel trace_id / span_id shapes for correlation.
TRACE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{16}$")


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class LlmSpan(Protocol):
    def set_usage(self, input_tokens: int, output_tokens: int) -> None: ...
    def set_finish_reason(self, reason: str) -> None: ...
    def record_error(self, code: str, message: str) -> None: ...


@runtime_checkable
class LlmTrace(Protocol):
    def start(
        self, operation: str, model_handle: str, prompt_fingerprint: str
    ) -> AbstractContextManager[LlmSpan]: ...


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
class LlmTraceInvariantError(ValueError):
    """Raised when a runtime call violates an LlmTrace invariant."""


def validate_operation(operation: str) -> str:
    if not isinstance(operation, str) or not operation.strip():
        raise LlmTraceInvariantError(
            "LLMTRACE-INV-01: operation MUST be a non-empty string."
        )
    return operation


def validate_model_handle(handle: str) -> str:
    if not isinstance(handle, str) or not handle.strip():
        raise LlmTraceInvariantError(
            "LLMTRACE-INV-02: model_handle MUST be a non-empty string so "
            "gen_ai.request.model is set."
        )
    return handle


def validate_prompt_fingerprint(fp: str) -> str:
    if not isinstance(fp, str) or not fp.strip():
        raise LlmTraceInvariantError(
            "LLMTRACE-INV-03: prompt_fingerprint MUST be a non-empty string "
            "to correlate with PromptTemplate version."
        )
    return fp


def validate_semconv_key(key: str) -> str:
    """LLMTRACE-INV-02: attribute keys MUST use OTel GenAI namespace."""
    if not isinstance(key, str) or not key:
        raise LlmTraceInvariantError(
            "LLMTRACE-INV-02: attribute key MUST be a non-empty string."
        )
    if not key.startswith(GEN_AI_ALLOWED_PREFIX):
        raise LlmTraceInvariantError(
            f"LLMTRACE-INV-02: attribute key {key!r} MUST start with "
            f"{GEN_AI_ALLOWED_PREFIX!r} (OTel GenAI SemConv 1.27+)."
        )
    return key


def validate_finish_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason:
        raise LlmTraceInvariantError(
            "LLMTRACE-INV-02: finish_reason MUST be a non-empty string."
        )
    if reason not in FINISH_REASONS:
        raise LlmTraceInvariantError(
            f"LLMTRACE-INV-02: finish_reason MUST be one of "
            f"{sorted(FINISH_REASONS)}, got {reason!r}."
        )
    return reason


def validate_token_count(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LlmTraceInvariantError(
            f"LLMTRACE-INV-02: {name} MUST be a non-negative int, got "
            f"{type(value).__name__}."
        )
    if value < 0:
        raise LlmTraceInvariantError(
            f"LLMTRACE-INV-02: {name} MUST be >= 0, got {value}."
        )
    return value


# ---------------------------------------------------------------------------
# In-memory reference implementation
# ---------------------------------------------------------------------------
class _InMemoryLlmSpan:
    """Default in-memory LlmSpan used as the reference implementation.

    Thread-safe. Respects LLMTRACE-INV-03 (prompt_fingerprint required) and
    LLMTRACE-INV-04 (record_error MUST be invoked for provider errors).
    Privacy-first: prompt/response content is NEVER captured unless the
    parent tracer is constructed with capture_content=True.
    """

    def __init__(
        self,
        *,
        operation: str,
        model_handle: str,
        prompt_fingerprint: str,
        parent_span_id: str | None,
        span_id: str,
        trace_id: str,
        start_ns: int,
    ) -> None:
        self.operation: str = operation
        self.model_handle: str = model_handle
        self.prompt_fingerprint: str = prompt_fingerprint
        self.parent_span_id: str | None = parent_span_id
        self.span_id: str = span_id
        self.trace_id: str = trace_id
        self.start_ns: int = start_ns
        self.end_ns: int | None = None

        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.cache_read_input_tokens: int | None = None
        self.cache_creation_input_tokens: int | None = None
        self.finish_reason: str | None = None
        self.error_code: str | None = None
        self.error_message: str | None = None
        self.status_code: str = "UNSET"
        self.attributes: dict[str, object] = {
            GEN_AI_OPERATION_NAME: operation,
            GEN_AI_REQUEST_MODEL: model_handle,
            GEN_AI_PROMPT_FINGERPRINT: prompt_fingerprint,
        }
        self._lock = threading.Lock()

    # ----- Protocol surface --------------------------------------------------
    def set_usage(self, input_tokens: int, output_tokens: int) -> None:
        validate_token_count("input_tokens", input_tokens)
        validate_token_count("output_tokens", output_tokens)
        with self._lock:
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.attributes[GEN_AI_USAGE_INPUT_TOKENS] = input_tokens
            self.attributes[GEN_AI_USAGE_OUTPUT_TOKENS] = output_tokens

    def set_finish_reason(self, reason: str) -> None:
        validate_finish_reason(reason)
        with self._lock:
            self.finish_reason = reason
            # OTel GenAI uses list-valued finish_reasons.
            self.attributes[GEN_AI_RESPONSE_FINISH_REASONS] = [reason]

    def record_error(self, code: str, message: str) -> None:
        if not isinstance(code, str) or not code:
            raise LlmTraceInvariantError(
                "LLMTRACE-INV-04: error code MUST be a non-empty string."
            )
        if not isinstance(message, str):
            raise LlmTraceInvariantError(
                "LLMTRACE-INV-04: error message MUST be a string."
            )
        with self._lock:
            self.error_code = code
            self.error_message = message
            self.status_code = "ERROR"
            self.attributes["gen_ai.error.type"] = code
            self.attributes["gen_ai.error.message"] = message

    # ----- extended GenAI attrs (optional) ----------------------------------
    def set_cache_usage(
        self, cache_read_input_tokens: int, cache_creation_input_tokens: int
    ) -> None:
        validate_token_count("cache_read_input_tokens", cache_read_input_tokens)
        validate_token_count(
            "cache_creation_input_tokens", cache_creation_input_tokens
        )
        with self._lock:
            self.cache_read_input_tokens = cache_read_input_tokens
            self.cache_creation_input_tokens = cache_creation_input_tokens
            self.attributes[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] = (
                cache_read_input_tokens
            )
            self.attributes[GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS] = (
                cache_creation_input_tokens
            )

    def set_temperature(self, temperature: float) -> None:
        if isinstance(temperature, bool) or not isinstance(
            temperature, (int, float)
        ):
            raise LlmTraceInvariantError(
                "LLMTRACE-INV-02: temperature MUST be a number."
            )
        with self._lock:
            self.attributes[GEN_AI_REQUEST_TEMPERATURE] = float(temperature)

    def end(self, end_ns: int) -> None:
        with self._lock:
            if self.end_ns is not None:
                return
            if end_ns < self.start_ns:
                raise LlmTraceInvariantError(
                    "LLMTRACE-INV-01: end timestamp MUST NOT precede start."
                )
            self.end_ns = end_ns
            if self.status_code == "UNSET":
                self.status_code = "OK"


class InMemoryLlmTrace:
    """Reference LlmTrace implementation.

    Maintains a per-tracer in-memory list of emitted spans. Enforces parent/
    child nesting (LLMTRACE-INV-05) via an explicit stack of active spans.
    Privacy-first: `capture_content` is False by default; callers who flip it
    are responsible for downstream redaction.
    """

    def __init__(
        self,
        *,
        system: str = "internal",
        capture_content: bool = False,
    ) -> None:
        self._spans: list[_InMemoryLlmSpan] = []
        self._lock = threading.Lock()
        self._active: list[_InMemoryLlmSpan] = []
        self._trace_id: str = _new_trace_id()
        self._counter: int = 0
        self._capture_content: bool = bool(capture_content)
        self._system: str = system

    # ----- catalog API -------------------------------------------------------
    def start(
        self, operation: str, model_handle: str, prompt_fingerprint: str
    ) -> AbstractContextManager[LlmSpan]:
        validate_operation(operation)
        validate_model_handle(model_handle)
        validate_prompt_fingerprint(prompt_fingerprint)

        parent_span_id: str | None
        with self._lock:
            self._counter += 1
            span_id = f"{self._counter:016x}"
            parent_span_id = self._active[-1].span_id if self._active else None
        span = _InMemoryLlmSpan(
            operation=operation,
            model_handle=model_handle,
            prompt_fingerprint=prompt_fingerprint,
            parent_span_id=parent_span_id,
            span_id=span_id,
            trace_id=self._trace_id,
            start_ns=time.monotonic_ns(),
        )
        span.attributes[GEN_AI_SYSTEM] = self._system

        with self._lock:
            self._spans.append(span)
            self._active.append(span)

        captured = self._capture_content

        @contextmanager
        def _cm() -> Iterator[LlmSpan]:
            try:
                yield span
            except BaseException as exc:
                # LLMTRACE-INV-04: record_error MUST be invoked before exit.
                if span.error_code is None:
                    span.record_error(
                        code=type(exc).__name__,
                        message="" if not captured else str(exc),
                    )
                raise
            finally:
                span.end(time.monotonic_ns())
                with self._lock:
                    # LLMTRACE-INV-05: pop only if top-of-stack matches.
                    if self._active and self._active[-1] is span:
                        self._active.pop()

        return _cm()

    # ----- observability hooks ----------------------------------------------
    @property
    def spans(self) -> tuple[_InMemoryLlmSpan, ...]:
        with self._lock:
            return tuple(self._spans)

    @property
    def active_depth(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def capture_content(self) -> bool:
        return self._capture_content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_TRACE_COUNTER_LOCK = threading.Lock()
_TRACE_COUNTER: int = 0


def _new_trace_id() -> str:
    global _TRACE_COUNTER  # noqa: PLW0603 — module-local counter, not global state
    with _TRACE_COUNTER_LOCK:
        _TRACE_COUNTER += 1
        return f"{_TRACE_COUNTER:032x}"


def validate_attributes_match_semconv(attrs: Mapping[str, object]) -> None:
    """LLMTRACE-INV-02: every attribute key MUST be gen_ai.* namespaced."""
    for key in attrs:
        validate_semconv_key(key)


def assert_required_semconv_present(attrs: Mapping[str, object]) -> None:
    """LLMTRACE-INV-02 + INV-03: required GenAI keys present on every span."""
    missing = [k for k in GEN_AI_REQUIRED_ATTRS if k not in attrs]
    if missing:
        raise LlmTraceInvariantError(
            f"LLMTRACE-INV-02/03: missing required GenAI attrs: {missing}"
        )


__all__ = [
    "FINISH_REASONS",
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_PROMPT_FINGERPRINT",
    "GEN_AI_REQUEST_MODEL",
    "GEN_AI_REQUEST_TEMPERATURE",
    "GEN_AI_REQUIRED_ATTRS",
    "GEN_AI_RESPONSE_FINISH_REASONS",
    "GEN_AI_SYSTEM",
    "GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS",
    "GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS",
    "GEN_AI_USAGE_INPUT_TOKENS",
    "GEN_AI_USAGE_OUTPUT_TOKENS",
    "SPAN_ID_RE",
    "TRACE_ID_RE",
    "InMemoryLlmTrace",
    "LlmSpan",
    "LlmTrace",
    "LlmTraceInvariantError",
    "assert_required_semconv_present",
    "validate_attributes_match_semconv",
    "validate_finish_reason",
    "validate_model_handle",
    "validate_operation",
    "validate_prompt_fingerprint",
    "validate_semconv_key",
    "validate_token_count",
]
