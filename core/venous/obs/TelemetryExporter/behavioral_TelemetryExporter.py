"""Behavioral scenarios for TelemetryExporter."""

from __future__ import annotations

import pytest

from TelemetryExporter import (
    ExportResult,
    InMemoryTelemetryExporter,
    Signal,
    TelemetryExporterInvariantError,
)


def test_scenario_flush_on_shutdown() -> None:
    ex = InMemoryTelemetryExporter()
    ex.export([{"x": 1}], timeout_s=1.0)
    assert ex.force_flush(timeout_s=1.0)
    assert ex.shutdown(timeout_s=1.0)


def test_scenario_post_shutdown_rejects_export() -> None:
    ex = InMemoryTelemetryExporter()
    ex.shutdown(timeout_s=1.0)
    with pytest.raises(TelemetryExporterInvariantError):
        ex.export([], timeout_s=1.0)


def test_scenario_auth_headers_redacted_in_logs() -> None:
    ex = InMemoryTelemetryExporter()
    ex.emit_log("send", {"Authorization": "Bearer SECRET"})
    assert ex._logs_emitted[0]["attributes"]["Authorization"] == "[REDACTED]"


def test_scenario_counters_track_signal_and_result() -> None:
    ex = InMemoryTelemetryExporter(signal=Signal.METRICS)
    ex.export([{"x": 1}], timeout_s=1.0)
    assert ex.counter[("metrics", "success")] == 1


def test_scenario_batches_preserved_in_order() -> None:
    ex = InMemoryTelemetryExporter()
    for i in range(5):
        ex.export([{"i": i}], timeout_s=1.0)
    ids = [b[0]["i"] for b in ex.exported_batches]  # type: ignore[index]
    assert ids == [0, 1, 2, 3, 4]


def test_scenario_result_is_enum() -> None:
    ex = InMemoryTelemetryExporter()
    r = ex.export([{"x": 1}], timeout_s=1.0)
    assert isinstance(r, ExportResult)
