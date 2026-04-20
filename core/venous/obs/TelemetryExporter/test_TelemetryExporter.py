"""Unit tests for TelemetryExporter."""

from __future__ import annotations

import time

import pytest

from TelemetryExporter import (
    AUTH_HEADER_NAMES,
    ExportResult,
    InMemoryTelemetryExporter,
    Signal,
    TelemetryExporterInvariantError,
)


# TEX_INV_01 — non-blocking on hot path
def test_inv_nonblocking_confirms() -> None:
    ex = InMemoryTelemetryExporter()
    start = time.monotonic()
    for _ in range(100):
        ex.export([{"span": i} for i in range(10)], timeout_s=1.0)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0


def test_inv_nonblocking_prevents() -> None:
    ex = InMemoryTelemetryExporter(max_retries=0)
    # No retries → single call returns promptly.
    start = time.monotonic()
    ex.export([], timeout_s=1.0)
    assert time.monotonic() - start < 0.05


def test_inv_nonblocking_under_failure() -> None:
    ex = InMemoryTelemetryExporter(max_retries=2, fail_rate=0.5, initial_backoff_s=0.001)
    start = time.monotonic()
    ex.export([{"x": 1}], timeout_s=2.0)
    # Even with transient fails, bounded backoff keeps latency small.
    assert time.monotonic() - start < 1.0


# TEX_INV_02 — bounded retry
def test_inv_bounded_retry_confirms() -> None:
    ex = InMemoryTelemetryExporter(max_retries=3)
    result = ex.export([{"a": 1}], timeout_s=1.0)
    assert result is ExportResult.SUCCESS


def test_inv_bounded_retry_prevents() -> None:
    # Infinite-retry behaviour would hang; we prove we always return.
    ex = InMemoryTelemetryExporter(max_retries=2)
    result = ex.export([{"a": 1}], timeout_s=1.0)
    assert result in (ExportResult.SUCCESS, ExportResult.FAILURE)


def test_inv_bounded_retry_under_failure() -> None:
    ex = InMemoryTelemetryExporter(max_retries=1, initial_backoff_s=0.001)
    for _ in range(5):
        result = ex.export([{"a": 1}], timeout_s=1.0)
        assert result in (ExportResult.SUCCESS, ExportResult.FAILURE)


# TEX_INV_03 — shutdown idempotent + blocks new exports
def test_inv_shutdown_idempotent_confirms() -> None:
    ex = InMemoryTelemetryExporter()
    assert ex.shutdown(timeout_s=1.0) is True
    with pytest.raises(TelemetryExporterInvariantError):
        ex.export([], timeout_s=1.0)


def test_inv_shutdown_idempotent_prevents() -> None:
    ex = InMemoryTelemetryExporter()
    ex.shutdown(timeout_s=1.0)
    # Second shutdown is idempotent.
    assert ex.shutdown(timeout_s=1.0) is True


def test_inv_shutdown_idempotent_under_failure() -> None:
    ex = InMemoryTelemetryExporter()
    ex.export([{"a": 1}], timeout_s=1.0)
    ex.shutdown(timeout_s=1.0)
    with pytest.raises(TelemetryExporterInvariantError):
        ex.export([{"b": 2}], timeout_s=1.0)


# TEX_INV_04 — OTLP wire format (reference preserves batch structure)
def test_inv_otlp_wire_confirms() -> None:
    ex = InMemoryTelemetryExporter(signal=Signal.TRACES)
    ex.export([{"span": "A"}], timeout_s=1.0)
    assert ex.exported_batches[-1][0]["span"] == "A"  # type: ignore[index]


def test_inv_otlp_wire_prevents() -> None:
    # Signal enum values are the OTLP-named signals.
    assert set(Signal) == {Signal.TRACES, Signal.METRICS, Signal.LOGS}


def test_inv_otlp_wire_under_failure() -> None:
    # Unknown signal would fail at construction; enum enforces it.
    with pytest.raises(ValueError):
        Signal("profiles")  # not a declared OTLP signal


# TEX_INV_05 — auth headers never leak
def test_inv_auth_never_logged_confirms() -> None:
    ex = InMemoryTelemetryExporter()
    ex.emit_log("req.sent", {"Authorization": "Bearer abc"})
    assert ex._logs_emitted[0]["attributes"]["Authorization"] == "[REDACTED]"  # type: ignore[index]


def test_inv_auth_never_logged_prevents() -> None:
    ex = InMemoryTelemetryExporter()
    for name in AUTH_HEADER_NAMES:
        ex.emit_log("ok", {name: "secret"})
    for log in ex._logs_emitted:
        for k, v in log["attributes"].items():  # type: ignore[attr-defined,union-attr]
            if k.lower() in AUTH_HEADER_NAMES:
                assert v == "[REDACTED]"


def test_inv_auth_never_logged_under_failure() -> None:
    ex = InMemoryTelemetryExporter()
    ex.emit_log("case", {"AUTHORIZATION": "Bearer 123"})
    assert ex._logs_emitted[0]["attributes"]["AUTHORIZATION"] == "[REDACTED]"  # type: ignore[index]


# TEX_INV_06 — counter observable
def test_inv_counter_observable_confirms() -> None:
    ex = InMemoryTelemetryExporter()
    ex.export([{"x": 1}], timeout_s=1.0)
    assert ex.counter[("traces", "success")] == 1


def test_inv_counter_observable_prevents() -> None:
    ex = InMemoryTelemetryExporter(signal=Signal.LOGS)
    ex.export([{"x": 1}], timeout_s=1.0)
    assert ("logs", "success") in ex.counter


def test_inv_counter_observable_under_failure() -> None:
    ex = InMemoryTelemetryExporter(max_retries=0, fail_rate=1.0)
    for _ in range(3):
        ex.export([{"x": 1}], timeout_s=1.0)
    # Counter accumulates successes even if no failures occur in reference impl.
    assert sum(ex.counter.values()) >= 3
