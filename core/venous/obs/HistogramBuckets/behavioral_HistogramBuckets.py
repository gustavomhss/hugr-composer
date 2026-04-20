"""Behavioral scenarios for HistogramBuckets."""

from __future__ import annotations

import pytest

from HistogramBuckets import HistogramBuckets, HistogramBucketsInvariantError


def test_scenario_latency_preset() -> None:
    preset = HistogramBuckets.latency_ms_default()
    assert preset.unit == "ms"
    assert 1.0 in preset.boundaries


def test_scenario_payload_preset() -> None:
    preset = HistogramBuckets.payload_bytes_default()
    assert preset.unit == "By"


def test_scenario_bucket_cap_enforced() -> None:
    bounds = tuple(float(i) for i in range(1, 25))
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="too_many", unit="ms", boundaries=bounds)


def test_scenario_unit_mismatch_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="m", unit="seconds", boundaries=(1.0, 5.0))


def test_scenario_frozen_preset_used_verbatim() -> None:
    a = HistogramBuckets.latency_ms_default()
    b = HistogramBuckets.latency_ms_default()
    assert a.boundaries == b.boundaries


def test_scenario_custom_boundaries_authored() -> None:
    b = HistogramBuckets(name="custom", unit="ms",
                         boundaries=(0.5, 2.0, 10.0, 50.0, 250.0, 1000.0))
    assert len(b.boundaries) == 6
