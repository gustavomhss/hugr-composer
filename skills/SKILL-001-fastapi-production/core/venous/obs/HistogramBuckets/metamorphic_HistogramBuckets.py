"""Metamorphic + differential for HistogramBuckets."""

from __future__ import annotations

from HistogramBuckets import HistogramBuckets


def test_metamorphic_latency_preset_stable() -> None:
    first = HistogramBuckets.latency_ms_default().boundaries
    for _ in range(5):
        assert HistogramBuckets.latency_ms_default().boundaries == first


def test_metamorphic_payload_preset_stable() -> None:
    first = HistogramBuckets.payload_bytes_default().boundaries
    for _ in range(5):
        assert HistogramBuckets.payload_bytes_default().boundaries == first


def test_metamorphic_sorted_ascending() -> None:
    preset = HistogramBuckets.latency_ms_default()
    assert list(preset.boundaries) == sorted(preset.boundaries)


def test_differential_latency_vs_payload_units() -> None:
    assert HistogramBuckets.latency_ms_default().unit != HistogramBuckets.payload_bytes_default().unit


def test_metamorphic_custom_boundaries_preserved() -> None:
    input_bounds = (0.1, 0.5, 1.0, 10.0, 100.0)
    b = HistogramBuckets(name="c", unit="ms", boundaries=input_bounds)
    assert b.boundaries == input_bounds


def test_metamorphic_preset_and_custom_differ() -> None:
    preset = HistogramBuckets.latency_ms_default()
    custom = HistogramBuckets(name="c", unit="ms", boundaries=(10.0,))
    assert preset.boundaries != custom.boundaries
