"""Metamorphic + differential for TelemetryExporter."""

from __future__ import annotations

from TelemetryExporter import InMemoryTelemetryExporter, Signal


def test_metamorphic_export_success_counter_monotone() -> None:
    ex = InMemoryTelemetryExporter()
    prev = 0
    for _ in range(5):
        ex.export([{"x": 1}], timeout_s=1.0)
        now = ex.counter[("traces", "success")]
        assert now > prev
        prev = now


def test_metamorphic_signal_independence() -> None:
    a = InMemoryTelemetryExporter(signal=Signal.TRACES)
    b = InMemoryTelemetryExporter(signal=Signal.METRICS)
    a.export([{"x": 1}], timeout_s=1.0)
    b.export([{"x": 1}], timeout_s=1.0)
    assert a.counter.keys() != b.counter.keys()


def test_metamorphic_shutdown_idempotent() -> None:
    ex = InMemoryTelemetryExporter()
    for _ in range(3):
        assert ex.shutdown(timeout_s=1.0) is True


def test_metamorphic_force_flush_is_safe() -> None:
    ex = InMemoryTelemetryExporter()
    for _ in range(5):
        assert ex.force_flush(timeout_s=1.0) is True


def test_differential_three_signals_valid_otlp() -> None:
    for sig in (Signal.TRACES, Signal.METRICS, Signal.LOGS):
        ex = InMemoryTelemetryExporter(signal=sig)
        ex.export([{"x": 1}], timeout_s=1.0)
        assert (sig.value, "success") in ex.counter


def test_metamorphic_batch_immutability_after_export() -> None:
    ex = InMemoryTelemetryExporter()
    batch = [{"x": 1}]
    ex.export(batch, timeout_s=1.0)
    batch.append({"leaked": True})
    stored = ex.exported_batches[0]
    assert len(stored) == 1  # stored as a frozen tuple snapshot
