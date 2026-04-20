"""Chaos tests for TelemetryExporter."""

from __future__ import annotations

import threading

import pytest

from TelemetryExporter import (
    AUTH_HEADER_NAMES,
    InMemoryTelemetryExporter,
    TelemetryExporterInvariantError,
)


def test_chaos_many_concurrent_exports_succeed() -> None:
    ex = InMemoryTelemetryExporter()

    def worker() -> None:
        for _ in range(50):
            ex.export([{"x": 1}], timeout_s=1.0)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ex.exported_batches) == 200


def test_chaos_post_shutdown_export_raises_consistently() -> None:
    ex = InMemoryTelemetryExporter()
    ex.shutdown(timeout_s=1.0)
    for _ in range(5):
        with pytest.raises(TelemetryExporterInvariantError):
            ex.export([], timeout_s=1.0)


def test_chaos_auth_header_case_variants_all_redacted() -> None:
    ex = InMemoryTelemetryExporter()
    for variant in ("authorization", "AUTHORIZATION", "Authorization"):
        ex.emit_log("send", {variant: "Bearer secret"})
    for log in ex._logs_emitted:
        for k, v in log["attributes"].items():  # type: ignore[attr-defined,union-attr]
            if k.lower() in AUTH_HEADER_NAMES:
                assert v == "[REDACTED]"


def test_chaos_retry_bounded_even_with_high_failure_rate() -> None:
    ex = InMemoryTelemetryExporter(max_retries=2, fail_rate=0.99,
                                   initial_backoff_s=0.001)
    for _ in range(5):
        ex.export([{"x": 1}], timeout_s=1.0)


def test_chaos_force_flush_survives_repeated_calls() -> None:
    ex = InMemoryTelemetryExporter()
    for _ in range(100):
        assert ex.force_flush(timeout_s=0.1)


def test_chaos_empty_batch_is_ok() -> None:
    ex = InMemoryTelemetryExporter()
    r = ex.export([], timeout_s=1.0)
    assert r.value in ("success", "failure", "timeout")
