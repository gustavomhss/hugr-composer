"""StructuredLogger primitive — key/value log records, fixed taxonomy, JSON lines.

Invariants (all IDs referenced in docstrings):

- LOG-INV-01: every record MUST be a single line of valid UTF-8 JSON with 'ts',
  'level', 'event', plus caller-provided fields.
- LOG-INV-02: level SHALL be one of DEBUG/INFO/WARN/ERROR; TRACE/FATAL FORBIDDEN.
- LOG-INV-03: when a span is active, record MUST include trace_id/span_id in hex.
- LOG-INV-04: printf-style / f-string formatting inside event message is FORBIDDEN.
- LOG-INV-05: registered redaction patterns (authorization, bearer, PAN) MUST be
  replaced with '[REDACTED]' before serialization.
- LOG-INV-06: bind() NEVER mutates the parent logger; returns a new immutable logger.

No I/O at import.
"""

from __future__ import annotations

import contextvars
import json
import re
import threading
import time
from collections.abc import Mapping
from typing import Any, Final, Protocol, runtime_checkable

ALLOWED_LEVELS: Final[frozenset[str]] = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})
FORBIDDEN_LEVELS: Final[frozenset[str]] = frozenset({"TRACE", "FATAL", "NOTSET", "CRITICAL"})
FORMATTING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"%[sdif]"),          # printf legacy
    re.compile(r"\{[^{}]*\}"),       # f-string / str.format
)
DEFAULT_REDACTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"(?i)authorization:\s*[A-Za-z0-9._-]+"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),  # card PAN
)
REDACTED: Final[str] = "[REDACTED]"


class LogInvariantError(ValueError):
    """Runtime invariant violation on a log record."""


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------
@runtime_checkable
class StructuredLogger(Protocol):
    def debug(self, event: str, **fields: Any) -> None: ...
    def info(self, event: str, **fields: Any) -> None: ...
    def warn(self, event: str, **fields: Any) -> None: ...
    def error(self, event: str, *, exc: BaseException | None = None, **fields: Any) -> None: ...
    def bind(self, **fields: Any) -> StructuredLogger: ...
    def with_context(self, context: Mapping[str, Any]) -> StructuredLogger: ...


def validate_event_message(event: str) -> str:
    """LOG-INV-04: event MUST NOT contain formatting placeholders."""
    if not isinstance(event, str) or not event:
        raise LogInvariantError("LOG-INV-01: event MUST be a non-empty string.")
    for pat in FORMATTING_PATTERNS:
        if pat.search(event):
            raise LogInvariantError(
                "LOG-INV-04: event message MUST NOT contain %-formatting or "
                "f-string placeholders; pass values as typed fields."
            )
    return event


def validate_level(level: str) -> str:
    if level not in ALLOWED_LEVELS:
        raise LogInvariantError(
            f"LOG-INV-02: level MUST be one of {sorted(ALLOWED_LEVELS)}; got {level!r}."
        )
    return level


def redact(value: str, patterns: tuple[re.Pattern[str], ...] = DEFAULT_REDACTION_PATTERNS) -> str:
    """LOG-INV-05: apply all redaction patterns."""
    for pat in patterns:
        value = pat.sub(REDACTED, value)
    return value


# ---------------------------------------------------------------------------
# Context propagation helper — MUST NOT block / mutate on error
# ---------------------------------------------------------------------------
class _SpanContext:
    """Minimal context carrier used by StructuredLogger.

    LOG-INV-03 correctness: uses `contextvars.ContextVar` (NOT
    `threading.local`) so concurrent asyncio coroutines sharing a thread
    each observe their own span context. `threading.local` would let one
    task's trace_id bleed into another's log line when both run on the
    same event-loop thread.

    Kept here to avoid a hard dependency on Tracer; real deployments inject a
    Tracer adapter that yields trace_id/span_id via a context var.
    """

    def __init__(self) -> None:
        self._trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "structuredlogger.trace_id", default=None,
        )
        self._span_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "structuredlogger.span_id", default=None,
        )

    def set(self, trace_id: str | None, span_id: str | None) -> None:
        self._trace_var.set(trace_id)
        self._span_var.set(span_id)

    def get(self) -> tuple[str | None, str | None]:
        return (self._trace_var.get(), self._span_var.get())


_DEFAULT_CONTEXT = _SpanContext()


class InMemoryStructuredLogger:
    """Reference StructuredLogger — emits JSON lines to an internal buffer.

    Real deployments back this with a write-behind queue (WriteAdapter).
    """

    def __init__(
        self,
        *,
        bound: Mapping[str, Any] | None = None,
        context: _SpanContext | None = None,
        redaction_patterns: tuple[re.Pattern[str], ...] = DEFAULT_REDACTION_PATTERNS,
    ) -> None:
        self._bound: dict[str, Any] = dict(bound or {})
        self._context = context or _DEFAULT_CONTEXT
        self._redaction = redaction_patterns
        self._records: list[str] = []
        self._lock = threading.Lock()

    # ----- mutation-free bind / with_context -------------------------------
    def bind(self, **fields: Any) -> InMemoryStructuredLogger:
        merged = {**self._bound, **fields}
        # LOG-INV-06: new immutable instance — parent unchanged.
        return InMemoryStructuredLogger(
            bound=merged,
            context=self._context,
            redaction_patterns=self._redaction,
        )

    def with_context(self, context: Mapping[str, Any]) -> InMemoryStructuredLogger:
        return self.bind(**context)

    # ----- emission ---------------------------------------------------------
    def _emit(self, level: str, event: str, fields: Mapping[str, Any]) -> None:
        validate_level(level)
        validate_event_message(event)
        record: dict[str, Any] = {
            "ts": time.time(),
            "level": level,
            "event": event,
            **self._bound,
            **fields,
        }
        trace_id, span_id = self._context.get()
        if trace_id:
            record["trace_id"] = trace_id
        if span_id:
            record["span_id"] = span_id
        # LOG-INV-05: redact every str value; stringify non-JSON-safe values.
        for k, v in list(record.items()):
            if isinstance(v, bytes):
                record[k] = f"<{len(v)}-byte-blob>"
            elif isinstance(v, str):
                record[k] = redact(v, self._redaction)
        line = json.dumps(record, ensure_ascii=True, sort_keys=False, default=str)
        with self._lock:
            self._records.append(line)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit("DEBUG", event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit("INFO", event, fields)

    def warn(self, event: str, **fields: Any) -> None:
        self._emit("WARN", event, fields)

    def error(self, event: str, *, exc: BaseException | None = None, **fields: Any) -> None:
        enriched = dict(fields)
        if exc is not None:
            enriched["exception.type"] = type(exc).__name__
            enriched["exception.message"] = redact(str(exc), self._redaction)
        self._emit("ERROR", event, enriched)

    # ----- observability hooks ---------------------------------------------
    @property
    def records(self) -> list[str]:
        with self._lock:
            return list(self._records)

    def activate_span(self, trace_id: str, span_id: str) -> None:
        """Test helper to simulate an active span."""
        self._context.set(trace_id, span_id)

    def clear_span(self) -> None:
        self._context.set(None, None)


__all__ = [
    "ALLOWED_LEVELS",
    "DEFAULT_REDACTION_PATTERNS",
    "FORBIDDEN_LEVELS",
    "REDACTED",
    "InMemoryStructuredLogger",
    "LogInvariantError",
    "StructuredLogger",
    "redact",
    "validate_event_message",
    "validate_level",
]
