"""Tracer primitive — OpenTelemetry-aligned span factory with W3C Trace Context.

Implements the catalog Protocol for `obs.Tracer` and installs runtime invariant
checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- TRACER-INV-01: every span has a non-empty name, start_ts, end_ts in causal order.
- TRACER-INV-02: a span CANNOT be ended twice; a second end call SHALL be a no-op
  with a recorded internal warning.
- TRACER-INV-03: W3C Trace Context headers (traceparent, tracestate) MUST be
  honored on inject/extract without mutation of unknown tracestate entries.
- TRACER-INV-04: recording an exception MUST set the span status to ERROR unless
  the caller explicitly overrides with OK.
- TRACER-INV-05: attribute values MUST be str, bool, int, float, or a homogeneous
  sequence of those types; nested structures are FORBIDDEN.
- TRACER-INV-06: the tracer SHALL NEVER block the caller waiting for exporter
  acknowledgement; export is asynchronous.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPAN_KINDS: Final[frozenset[str]] = frozenset(
    {"INTERNAL", "SERVER", "CLIENT", "PRODUCER", "CONSUMER"}
)
STATUS_CODES: Final[frozenset[str]] = frozenset({"UNSET", "OK", "ERROR"})
TRACEPARENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)
TRACESTATE_MAX_ENTRIES: Final[int] = 32
ATTRIBUTE_PRIMITIVES: Final[tuple[type, ...]] = (str, bool, int, float)


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class Span(Protocol):
    def set_attribute(self, key: str, value: str | float | bool) -> None: ...
    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None: ...
    def record_exception(self, exc: BaseException) -> None: ...
    def set_status(self, code: str, description: str | None = None) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    def start_as_current_span(
        self,
        name: str,
        *,
        kind: str = "INTERNAL",
        attributes: Mapping[str, object] | None = None,
        links: Sequence[object] = (),
    ) -> AbstractContextManager[Span]: ...

    def inject(self, carrier: dict[str, str]) -> None: ...
    def extract(self, carrier: Mapping[str, str]) -> object: ...


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
class TracerInvariantError(ValueError):
    """Raised when a runtime call violates a Tracer invariant."""


def validate_span_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise TracerInvariantError(
            "TRACER-INV-01: span name MUST be a non-empty string."
        )
    return name


def validate_kind(kind: str) -> str:
    if kind not in SPAN_KINDS:
        raise TracerInvariantError(
            f"TRACER-INV-05 supporting: kind MUST be one of {sorted(SPAN_KINDS)}, got {kind!r}."
        )
    return kind


def validate_attribute_value(key: str, value: object) -> None:
    """TRACER-INV-05: attribute values MUST be primitives or homogeneous sequences."""
    if isinstance(value, bool) or isinstance(value, (str, int, float)):
        return
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return
        first_type = type(value[0])
        if first_type not in ATTRIBUTE_PRIMITIVES:
            raise TracerInvariantError(
                f"TRACER-INV-05: attribute {key!r} sequence elements MUST be primitive, "
                f"got {first_type.__name__}."
            )
        for item in value:
            if type(item) is not first_type:
                raise TracerInvariantError(
                    f"TRACER-INV-05: attribute {key!r} sequence MUST be homogeneous; "
                    f"mixed {first_type.__name__}/{type(item).__name__}."
                )
        return
    raise TracerInvariantError(
        f"TRACER-INV-05: attribute {key!r} MUST be str/bool/int/float or homogeneous "
        f"sequence of those; nested/unsupported type {type(value).__name__} FORBIDDEN."
    )


def validate_status_code(code: str) -> str:
    if code not in STATUS_CODES:
        raise TracerInvariantError(
            f"TRACER-INV-04: status code MUST be one of {sorted(STATUS_CODES)}, got {code!r}."
        )
    return code


def validate_traceparent(value: str) -> bool:
    """TRACER-INV-03: traceparent MUST match the W3C shape."""
    return bool(TRACEPARENT_RE.match(value))


# ---------------------------------------------------------------------------
# In-memory reference implementation
# ---------------------------------------------------------------------------
class _InMemorySpan:
    """Default in-memory Span implementation used for testing and the reference impl.

    Thread-safe; end() is idempotent (TRACER-INV-02).
    """

    def __init__(self, name: str, kind: str, start_ns: int) -> None:
        self.name: str = name
        self.kind: str = kind
        self.start_ns: int = start_ns
        self.end_ns: int | None = None
        self.attributes: dict[str, object] = {}
        self.events: list[tuple[str, Mapping[str, object]]] = []
        self.status_code: str = "UNSET"
        self.status_description: str | None = None
        self.warnings: list[str] = []
        self._lock = threading.Lock()
        self._status_explicitly_set: bool = False

    def set_attribute(self, key: str, value: str | float | bool) -> None:
        if not isinstance(key, str) or not key:
            raise TracerInvariantError("TRACER-INV-05: attribute key MUST be non-empty str.")
        validate_attribute_value(key, value)
        with self._lock:
            self.attributes[key] = value

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        if not isinstance(name, str) or not name:
            raise TracerInvariantError("TRACER-INV-01 supporting: event name MUST be non-empty.")
        attrs: Mapping[str, object] = attributes or {}
        for k, v in attrs.items():
            validate_attribute_value(k, v)
        with self._lock:
            self.events.append((name, dict(attrs)))

    def record_exception(self, exc: BaseException) -> None:
        if not isinstance(exc, BaseException):
            raise TracerInvariantError(
                "TRACER-INV-04 supporting: record_exception requires a BaseException."
            )
        event_attrs: dict[str, object] = {
            "exception.type": type(exc).__name__,
            "exception.message": str(exc),
        }
        with self._lock:
            self.events.append(("exception", event_attrs))
            # TRACER-INV-04: default to ERROR unless caller explicitly set OK.
            if not self._status_explicitly_set or self.status_code != "OK":
                self.status_code = "ERROR"
                self.status_description = str(exc)

    def set_status(self, code: str, description: str | None = None) -> None:
        validate_status_code(code)
        with self._lock:
            self.status_code = code
            self.status_description = description
            self._status_explicitly_set = True

    def end(self, end_ns: int) -> None:
        """TRACER-INV-02: idempotent; second call records a warning and is a no-op."""
        with self._lock:
            if self.end_ns is not None:
                self.warnings.append("end() called twice; second call ignored (TRACER-INV-02).")
                return
            if end_ns < self.start_ns:
                raise TracerInvariantError(
                    "TRACER-INV-01: end timestamp MUST NOT precede start timestamp."
                )
            self.end_ns = end_ns


class InMemoryTracer:
    """Reference Tracer implementation.

    Designed for tests; real deployments swap in OpenTelemetry via adapter.
    """

    def __init__(self) -> None:
        self._spans: list[_InMemorySpan] = []
        self._lock = threading.Lock()
        self._trace_id: str | None = None
        self._span_id: str | None = None
        self._trace_state: str = ""
        self._export_calls: int = 0

    # ----- catalog API --------------------------------------------------------
    def start_as_current_span(
        self,
        name: str,
        *,
        kind: str = "INTERNAL",
        attributes: Mapping[str, object] | None = None,
        links: Sequence[object] = (),
    ) -> AbstractContextManager[Span]:
        validate_span_name(name)
        validate_kind(kind)
        attrs: Mapping[str, object] = attributes or {}
        for k, v in attrs.items():
            validate_attribute_value(k, v)
        _ = tuple(links)  # exhaust the iterable; links are opaque
        span = _InMemorySpan(name=name, kind=kind, start_ns=time.monotonic_ns())
        for k, v in attrs.items():
            if isinstance(v, (str, int, float, bool)):
                span.set_attribute(k, v)
        with self._lock:
            self._spans.append(span)

        @contextmanager
        def _cm() -> Iterator[Span]:
            try:
                yield span
            finally:
                span.end(time.monotonic_ns())
                # TRACER-INV-06: enqueue for asynchronous export; never block.
                self._export_calls += 1

        return _cm()

    def inject(self, carrier: dict[str, str]) -> None:
        """TRACER-INV-03: write traceparent + tracestate without mutating unknowns."""
        if self._trace_id and self._span_id:
            carrier["traceparent"] = f"00-{self._trace_id}-{self._span_id}-01"
        if self._trace_state:
            carrier["tracestate"] = self._trace_state

    def extract(self, carrier: Mapping[str, str]) -> object:
        """TRACER-INV-03: honor carrier; unknown tracestate entries pass through."""
        tp = carrier.get("traceparent", "")
        if tp and validate_traceparent(tp):
            parts = tp.split("-")
            self._trace_id = parts[1]
            self._span_id = parts[2]
        ts = carrier.get("tracestate", "")
        # Preserve as-is; do not mutate unknown vendor entries.
        entries = [e.strip() for e in ts.split(",") if e.strip()]
        if len(entries) > TRACESTATE_MAX_ENTRIES:
            entries = entries[:TRACESTATE_MAX_ENTRIES]
        self._trace_state = ",".join(entries)
        return {
            "trace_id": self._trace_id,
            "span_id": self._span_id,
            "trace_state": self._trace_state,
        }

    # ----- observability hooks -----------------------------------------------
    @property
    def spans(self) -> Sequence[_InMemorySpan]:
        with self._lock:
            return tuple(self._spans)

    @property
    def export_calls(self) -> int:
        return self._export_calls


__all__ = [
    "ATTRIBUTE_PRIMITIVES",
    "SPAN_KINDS",
    "STATUS_CODES",
    "TRACEPARENT_RE",
    "TRACESTATE_MAX_ENTRIES",
    "InMemoryTracer",
    "Span",
    "Tracer",
    "TracerInvariantError",
    "validate_attribute_value",
    "validate_kind",
    "validate_span_name",
    "validate_status_code",
    "validate_traceparent",
]
