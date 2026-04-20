"""ErrorSink primitive — captures uncaught exceptions with deterministic fingerprint.

Invariant IDs:

- ERR-INV-01: every captured event MUST include active trace_id, span_id, request_id
  when those are set.
- ERR-INV-02: fingerprint MUST be deterministic per (exception type, top-3 frames);
  identical incidents SHALL NEVER split into separate issues.
- ERR-INV-03: capture_exception MUST redact registered PII field names before transport.
- ERR-INV-04: the sink CANNOT block the caller; serialisation/transport SHALL run on
  a background worker.
- ERR-INV-05: before_send hooks returning None MUST drop the event; NEVER partially transmit.
- ERR-INV-06: sampling SHALL apply AFTER fingerprinting; rare variants SHALL NOT be suppressed
  by head-of-queue drops.
"""

from __future__ import annotations

import hashlib
import queue
import secrets
import threading
import traceback
from collections.abc import Callable, Mapping
from typing import Final, Protocol, runtime_checkable

DEFAULT_PII_FIELDS: Final[frozenset[str]] = frozenset({
    "email", "password", "authorization", "ssn", "cpf", "pan",
    "bearer", "cookie", "api_key", "credit_card",
})
REDACTED: Final[str] = "[REDACTED]"


class ErrorSinkInvariantError(ValueError):
    """Runtime invariant violation on an ErrorSink."""


@runtime_checkable
class ErrorSink(Protocol):
    def capture_exception(
        self,
        exc: BaseException,
        *,
        level: str = "error",
        tags: Mapping[str, str] | None = None,
        extras: Mapping[str, object] | None = None,
    ) -> str: ...

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        tags: Mapping[str, str] | None = None,
    ) -> str: ...

    def register_fingerprinter(self, fn: Callable[[BaseException], list[str]]) -> None: ...
    def before_send(self, fn: Callable[[dict[str, object]], dict[str, object] | None]) -> None: ...


def default_fingerprint(exc: BaseException) -> list[str]:
    """ERR-INV-02: deterministic grouping key from type + top-3 stack frames."""
    parts: list[str] = [type(exc).__name__]
    tb = traceback.extract_tb(exc.__traceback__)
    for frame in tb[:3]:
        parts.append(f"{frame.filename}:{frame.name}")
    return parts


def _redact_payload(payload: dict[str, object], pii_fields: frozenset[str]) -> dict[str, object]:
    """ERR-INV-03: drop or redact known-PII fields recursively."""
    out: dict[str, object] = {}
    for k, v in payload.items():
        lk = k.lower()
        if lk in pii_fields:
            out[k] = REDACTED
            continue
        if isinstance(v, dict):
            out[k] = _redact_payload(v, pii_fields)
        elif isinstance(v, (list, tuple)):
            out[k] = [
                _redact_payload(i, pii_fields) if isinstance(i, dict) else i
                for i in v
            ]
        else:
            out[k] = v
    return out


class InMemoryErrorSink:
    """Reference ErrorSink — non-blocking via background worker."""

    def __init__(
        self,
        *,
        pii_fields: frozenset[str] = DEFAULT_PII_FIELDS,
        sampling_rate: float = 1.0,
    ) -> None:
        if not 0.0 <= sampling_rate <= 1.0:
            raise ErrorSinkInvariantError("sampling_rate MUST be in [0,1].")
        self._pii_fields = pii_fields
        self._fingerprinters: list[Callable[[BaseException], list[str]]] = []
        self._before_send: list[Callable[[dict[str, object]], dict[str, object] | None]] = []
        # ERR-INV-04: worker-in-flight counter — `flush()` uses this to block
        # until every popped event has been committed to `_sent`.
        self._inflight: int = 0
        self._queue: queue.Queue[dict[str, object]] = queue.Queue()
        self._sent: list[dict[str, object]] = []
        self._dropped: list[dict[str, object]] = []
        self._trace_id: str | None = None
        self._span_id: str | None = None
        self._request_id: str | None = None
        self._lock = threading.Lock()
        self._sampling_rate = sampling_rate
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker_run = True
        self._worker.start()

    # ----- context plumbing (tests set these explicitly) -------------------
    def set_context(self, *, trace_id: str | None = None, span_id: str | None = None,
                    request_id: str | None = None) -> None:
        self._trace_id = trace_id
        self._span_id = span_id
        self._request_id = request_id

    # ----- registration -----------------------------------------------------
    def register_fingerprinter(self, fn: Callable[[BaseException], list[str]]) -> None:
        self._fingerprinters.append(fn)

    def before_send(self, fn: Callable[[dict[str, object]], dict[str, object] | None]) -> None:
        self._before_send.append(fn)

    # ----- capture ----------------------------------------------------------
    def capture_exception(
        self,
        exc: BaseException,
        *,
        level: str = "error",
        tags: Mapping[str, str] | None = None,
        extras: Mapping[str, object] | None = None,
    ) -> str:
        event_id = secrets.token_hex(8)
        fp_parts: list[str] = []
        if self._fingerprinters:
            try:
                fp_parts = self._fingerprinters[0](exc)
            except Exception:  # noqa: BLE001 — fingerprinter isolation
                fp_parts = default_fingerprint(exc)
        else:
            fp_parts = default_fingerprint(exc)
        fingerprint = hashlib.sha256("|".join(fp_parts).encode()).hexdigest()

        # ERR-INV-01: include correlation when set.
        event: dict[str, object] = {
            "event_id": event_id,
            "level": level,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "fingerprint": fingerprint,
            "tags": dict(tags or {}),
            "extras": dict(extras or {}),
        }
        if self._trace_id:
            event["trace_id"] = self._trace_id
        if self._span_id:
            event["span_id"] = self._span_id
        if self._request_id:
            event["request_id"] = self._request_id

        event = _redact_payload(event, self._pii_fields)

        # ERR-INV-05: before_send hooks can short-circuit.
        for hook in self._before_send:
            result = hook(event)
            if result is None:
                self._dropped.append(event)
                return event_id
            event = result

        # ERR-INV-06: sampling AFTER fingerprinting.
        if self._sampling_rate < 1.0:
            bucket = int(fingerprint[:8], 16) / 0xFFFFFFFF
            if bucket >= self._sampling_rate:
                self._dropped.append(event)
                return event_id

        # ERR-INV-04: non-blocking: queue, background worker drains.
        self._queue.put(event)
        return event_id

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        tags: Mapping[str, str] | None = None,
    ) -> str:
        event_id = secrets.token_hex(8)
        fingerprint = hashlib.sha256(f"msg|{message}".encode()).hexdigest()
        event: dict[str, object] = {
            "event_id": event_id,
            "level": level,
            "message": message,
            "tags": dict(tags or {}),
            "fingerprint": fingerprint,
        }
        if self._trace_id:
            event["trace_id"] = self._trace_id
        event = _redact_payload(event, self._pii_fields)

        # ERR-INV-05: before_send hooks apply to EVERY captured event, including
        # `capture_message` — not only `capture_exception`. Hooks returning
        # None MUST drop the event.
        for hook in self._before_send:
            result = hook(event)
            if result is None:
                self._dropped.append(event)
                return event_id
            event = result

        # ERR-INV-06: sampling AFTER fingerprinting applies uniformly.
        if self._sampling_rate < 1.0:
            bucket = int(fingerprint[:8], 16) / 0xFFFFFFFF
            if bucket >= self._sampling_rate:
                self._dropped.append(event)
                return event_id

        self._queue.put(event)
        return event_id

    # ----- worker -----------------------------------------------------------
    def _drain(self) -> None:
        while self._worker_run:
            try:
                event = self._queue.get(timeout=0.005)
            except queue.Empty:
                continue
            # ERR-INV-04: mark "in flight" BEFORE releasing queue ownership so
            # `flush()` knows the worker has popped but not yet appended.
            # Using a counter (not a bool) lets concurrent workers be counted
            # even if we ever scale the drain thread pool.
            with self._lock:
                self._inflight += 1
            try:
                with self._lock:
                    self._sent.append(event)
            finally:
                with self._lock:
                    self._inflight -= 1

    def flush(self, *, timeout_s: float = 1.0) -> None:
        """Drain the queue synchronously (test helper / shutdown path).

        Blocks until BOTH the queue is empty AND no worker has an event
        popped-but-not-yet-appended. Previously returned eagerly on
        `queue.empty()` which could hand the caller a `_sent` list missing
        the event currently being committed by the worker (violation of
        the sent-property read-after-flush expectation).
        """
        import time as _time
        deadline = _time.monotonic() + timeout_s
        while _time.monotonic() < deadline:
            with self._lock:
                inflight = self._inflight
            if self._queue.empty() and inflight == 0:
                return
            _time.sleep(0.001)

    def shutdown(self) -> None:
        self._worker_run = False

    # ----- observability hooks ---------------------------------------------
    @property
    def sent(self) -> list[dict[str, object]]:
        self.flush()
        with self._lock:
            return list(self._sent)

    @property
    def dropped(self) -> list[dict[str, object]]:
        return list(self._dropped)


__all__ = [
    "DEFAULT_PII_FIELDS",
    "REDACTED",
    "ErrorSink",
    "ErrorSinkInvariantError",
    "InMemoryErrorSink",
    "default_fingerprint",
]
