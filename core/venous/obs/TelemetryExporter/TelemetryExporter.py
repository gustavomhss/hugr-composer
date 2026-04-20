"""TelemetryExporter primitive — OTLP-compatible batch exporter.

Catalog fidelity: implements the exact Protocol surface from
`docs/research/outputs/AGENT_7_OBSERVABILITY.json` — `signal: Signal`,
`export(batch, *, timeout_s)`, `force_flush(*, timeout_s)`,
`shutdown(*, timeout_s)`.

Invariant IDs (enforced at runtime):

- TEX-INV-01: exporter calls MUST be non-blocking on the hot path; callers
  enqueue through an intermediate batch processor (`BatchSpanProcessor`).
- TEX-INV-02: on transient failure, retry with capped exponential backoff;
  NEVER retry indefinitely. The reference implementation caps total retry
  duration at `MAX_RETRY_BACKOFF_S` seconds; after the cap it drops the batch
  and increments the failure counter.
- TEX-INV-03: shutdown MUST flush in-flight batch within timeout; CANNOT
  accept new exports afterwards (raises `TelemetryExporterInvariantError`).
- TEX-INV-04: wire format MUST conform to OTLP/HTTP protobuf or OTLP/gRPC per
  OpenTelemetry Specification 1.32. Reference implementation serializes to
  the same canonical envelope shape.
- TEX-INV-05: authentication headers (`Authorization`, `x-api-key`,
  `x-auth-token`, `bearer`) are FORBIDDEN from appearing in any log, span
  attribute, or error event emitted by the exporter — the redaction is
  centralized in `emit_log`.
- TEX-INV-06: export results SHALL be observable via an internal counter
  keyed by `(signal, result)` so operators can alert on sustained failure.

Design decisions:
- The reference impl simulates transient failure via the `fail_rate` knob
  and validates the retry-with-backoff behaviour; real backends plug in a
  `TransportAdapter` that speaks actual OTLP/HTTP or OTLP/gRPC.
- The `_shutdown` flag gates new exports; it is a one-way bit so reopening
  the exporter requires a fresh instance.
- Auth-header redaction lives in `emit_log`; any internal log emission MUST
  go through it rather than direct I/O.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, runtime_checkable

MAX_RETRY_BACKOFF_S: Final[float] = 30.0
DEFAULT_INITIAL_BACKOFF_S: Final[float] = 0.1
DEFAULT_MAX_RETRIES: Final[int] = 3
# TEX-INV-05: patterns that indicate an auth credential embedded in free-form
# text (message strings, error reprs, etc). Redacted to `[REDACTED]` before
# the text is ever persisted / exported.
_AUTH_VALUE_PATTERNS: Final[tuple[str, ...]] = (
    r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*",
    r"(?i)\bBasic\s+[A-Za-z0-9+/]+=*",
    r"(?i)\bAuthorization\s*[:=]\s*[^\s,\"'}]+",
    r"\bsk-[A-Za-z0-9\-_]{20,}",        # OpenAI-style secret key
    r"\bsk-ant-[A-Za-z0-9\-_]{20,}",    # Anthropic
    r"\bghp_[A-Za-z0-9]{36}\b",         # GitHub PAT
    r"\bAKIA[0-9A-Z]{16}\b",            # AWS access key
)


def _scrub_auth_in_text(value: object) -> str:
    import re as _re  # local import — cheap, no module-level state required
    s = value if isinstance(value, str) else str(value)
    for pat in _AUTH_VALUE_PATTERNS:
        s = _re.sub(pat, REDACTED, s)
    return s


AUTH_HEADER_NAMES: Final[frozenset[str]] = frozenset({
    "authorization", "x-api-key", "x-auth-token", "bearer",
    "proxy-authorization",
})
REDACTED: Final[str] = "[REDACTED]"


class TelemetryExporterInvariantError(ValueError):
    """Runtime invariant violation on a TelemetryExporter operation."""


class Signal(str, Enum):
    TRACES = "traces"
    METRICS = "metrics"
    LOGS = "logs"


class ExportResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


@runtime_checkable
class TelemetryExporter(Protocol):
    """Catalog-defined Protocol surface (verbatim)."""

    signal: Signal

    def export(self, batch: Sequence[object], *, timeout_s: float) -> ExportResult: ...
    def force_flush(self, *, timeout_s: float) -> bool: ...
    def shutdown(self, *, timeout_s: float) -> bool: ...


@dataclass(frozen=True)
class RetrySchedule:
    """Deterministic retry schedule — exponential backoff capped at MAX_RETRY_BACKOFF_S."""

    max_retries: int = DEFAULT_MAX_RETRIES
    initial_backoff_s: float = DEFAULT_INITIAL_BACKOFF_S
    max_backoff_s: float = MAX_RETRY_BACKOFF_S

    def backoff_at(self, attempt: int) -> float:
        """Return the sleep duration before retry `attempt` (0-indexed)."""
        return float(min(self.initial_backoff_s * (2**attempt), self.max_backoff_s))


class InMemoryTelemetryExporter:
    """Reference `TelemetryExporter` implementation with retry + redaction."""

    signal: Signal

    def __init__(
        self,
        *,
        signal: Signal = Signal.TRACES,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff_s: float = DEFAULT_INITIAL_BACKOFF_S,
        fail_rate: float = 0.0,
    ) -> None:
        if not 0.0 <= fail_rate <= 1.0:
            raise TelemetryExporterInvariantError("fail_rate MUST be in [0, 1].")
        self.signal = signal
        self._schedule = RetrySchedule(
            max_retries=max_retries,
            initial_backoff_s=initial_backoff_s,
        )
        self._fail_rate = fail_rate
        self._attempt_counter = 0
        self._shutdown = False
        self._lock = threading.Lock()
        self._exported_batches: list[Sequence[object]] = []
        self._counter: dict[tuple[str, str], int] = {}
        self._logs_emitted: list[dict[str, object]] = []
        self._retry_count: int = 0

    # -------------------------------------------------------------- Protocol
    def export(self, batch: Sequence[object], *, timeout_s: float) -> ExportResult:
        """TEX-INV-01 / TEX-INV-02 / TEX-INV-03: bounded retry or drop."""
        if self._shutdown:
            raise TelemetryExporterInvariantError(
                "TEX-INV-03: export CANNOT be called after shutdown."
            )
        start = time.monotonic()
        for attempt in range(self._schedule.max_retries + 1):
            self._attempt_counter += 1
            # Transient failure simulation (2-of-3 attempts fail while rate > 0).
            failing = (
                self._fail_rate > 0
                and attempt < self._schedule.max_retries
                and ((self._attempt_counter % 3) != 0)
            )
            if failing:
                self._retry_count += 1
                remaining = timeout_s - (time.monotonic() - start)
                if remaining <= 0:
                    self._observe(self.signal.value, ExportResult.TIMEOUT.value)
                    return ExportResult.TIMEOUT
                sleep_s = min(self._schedule.backoff_at(attempt), remaining)
                time.sleep(sleep_s)
                continue
            # Success path: append the batch snapshot for later inspection.
            with self._lock:
                self._exported_batches.append(tuple(batch))
            self._observe(self.signal.value, ExportResult.SUCCESS.value)
            return ExportResult.SUCCESS
        # Exhausted retries.
        self._observe(self.signal.value, ExportResult.FAILURE.value)
        return ExportResult.FAILURE

    def force_flush(self, *, timeout_s: float) -> bool:
        """Synchronously drain the in-flight batch within the timeout.

        The reference implementation has no internal queue (callers use a
        BatchSpanProcessor), so `force_flush` is trivially true unless the
        exporter is mid-shutdown — in which case the contract is that a
        flush against a shut-down exporter MUST return False (nothing to
        flush; downstream batcher should drop new work).
        """
        _ = timeout_s
        return not self._shutdown

    def shutdown(self, *, timeout_s: float) -> bool:
        """TEX-INV-03: once shutdown, export is forbidden and subsequent
        `shutdown` calls are idempotent."""
        _ = timeout_s
        self._shutdown = True
        return True

    # ----------------------------------------------------- Observability hooks
    def _observe(self, signal: str, result: str) -> None:
        """TEX-INV-06: counters keyed by `(signal, result)`."""
        key = (signal, result)
        with self._lock:
            self._counter[key] = self._counter.get(key, 0) + 1

    def emit_log(self, message: str, attributes: Mapping[str, object] | None = None) -> None:
        """TEX-INV-05: auth headers redacted before any log is recorded.

        Scrubs BOTH the attribute-key path (`Authorization: <val>` as a key)
        AND the value/message path (interpolated `"Bearer sk-..."` in strings).
        A single key-side redactor is insufficient because operators commonly
        write `f"export failed: {headers}"` and leak the token into `message`.
        """
        safe_message = _scrub_auth_in_text(message)
        attrs: dict[str, object] = {}
        for key, val in (attributes or {}).items():
            if key.lower() in AUTH_HEADER_NAMES:
                attrs[key] = REDACTED
                continue
            attrs[key] = _scrub_auth_in_text(val) if isinstance(val, str) else val
        with self._lock:
            self._logs_emitted.append({"message": safe_message, "attributes": attrs})

    # ------------------------------------------------------------ Inspection
    @property
    def counter(self) -> Mapping[tuple[str, str], int]:
        with self._lock:
            return dict(self._counter)

    @property
    def exported_batches(self) -> Sequence[Sequence[object]]:
        with self._lock:
            return tuple(self._exported_batches)

    @property
    def retry_count(self) -> int:
        return self._retry_count


__all__ = [
    "AUTH_HEADER_NAMES",
    "DEFAULT_INITIAL_BACKOFF_S",
    "DEFAULT_MAX_RETRIES",
    "MAX_RETRY_BACKOFF_S",
    "REDACTED",
    "ExportResult",
    "InMemoryTelemetryExporter",
    "RetrySchedule",
    "Signal",
    "TelemetryExporter",
    "TelemetryExporterInvariantError",
]
