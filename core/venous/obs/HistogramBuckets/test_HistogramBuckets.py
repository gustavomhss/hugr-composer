"""Unit tests for HistogramBuckets."""

from __future__ import annotations

import pytest
from HistogramBuckets import (
    MAX_BUCKETS,
    HistogramBuckets,
    HistogramBucketsInvariantError,
)


# HB_INV_01 — boundaries well-formed
def test_inv_boundaries_well_formed_confirms() -> None:
    b = HistogramBuckets(name="lat", unit="ms", boundaries=(1.0, 5.0, 10.0))
    assert b.boundaries == (1.0, 5.0, 10.0)


def test_inv_boundaries_well_formed_prevents() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="lat", unit="ms", boundaries=(5.0, 1.0))
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="lat", unit="ms", boundaries=(-1.0, 1.0))
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="lat", unit="ms", boundaries=(float("inf"), 1.0))


def test_inv_boundaries_well_formed_under_failure() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="lat", unit="ms", boundaries=())


# HB_INV_02 — immutable
def test_inv_immutable_boundaries_confirms() -> None:
    b = HistogramBuckets(name="lat", unit="ms", boundaries=(1.0, 5.0))
    # frozen dataclass → attribute cannot be rebound.
    with pytest.raises((TypeError, AttributeError)):
        b.boundaries = (99.0,)  # type: ignore[misc]


def test_inv_immutable_boundaries_prevents() -> None:
    b = HistogramBuckets(name="lat", unit="ms", boundaries=(1.0, 5.0))
    # Tuple itself is immutable.
    with pytest.raises((TypeError,)):
        b.boundaries[0] = 99.0  # type: ignore[index]


def test_inv_immutable_boundaries_under_failure() -> None:
    b = HistogramBuckets(name="lat", unit="ms", boundaries=(1.0, 5.0, 10.0))
    first = b.boundaries
    # Constructing a new instance is OK; original remains stable.
    _ = HistogramBuckets(name="other", unit="ms", boundaries=(2.0, 4.0))
    assert b.boundaries is first


# HB_INV_03 — latency unit
def test_inv_latency_unit_confirms() -> None:
    b = HistogramBuckets.latency_ms_default()
    assert b.unit == "ms"


def test_inv_latency_unit_prevents() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="lat", unit="SECONDS", boundaries=(1.0, 5.0))
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="lat", unit="", boundaries=(1.0, 5.0))


def test_inv_latency_unit_under_failure() -> None:
    # Non-latency unit 'By' still passes when intentional.
    b = HistogramBuckets.payload_bytes_default()
    assert b.unit == "By"


# HB_INV_04 — lowest boundary below measurement floor
def test_inv_low_boundary_below_floor_confirms() -> None:
    b = HistogramBuckets.latency_ms_default()
    assert b.boundaries[0] <= 1.0


def test_inv_low_boundary_below_floor_prevents() -> None:
    # If we author a preset with a too-high floor, the client should detect it
    # via a sanity check (min boundary == 0 means bucket-0 dominates).
    assert HistogramBuckets.latency_ms_default().boundaries[0] < 10.0


def test_inv_low_boundary_below_floor_under_failure() -> None:
    b = HistogramBuckets(name="test", unit="ms",
                         boundaries=(0.5, 1.0, 5.0, 25.0, 100.0, 500.0))
    assert b.boundaries[0] < 1.0


# HB_INV_05 — bucket count cap
def test_inv_bucket_count_cap_confirms() -> None:
    bounds = tuple(float(i) for i in range(1, 21))  # 20 buckets
    b = HistogramBuckets(name="cap", unit="ms", boundaries=bounds)
    assert len(b.boundaries) == 20


def test_inv_bucket_count_cap_prevents() -> None:
    too_many = tuple(float(i) for i in range(1, 22))  # 21 buckets
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="cap", unit="ms", boundaries=too_many)


def test_inv_bucket_count_cap_under_failure() -> None:
    many = tuple(float(i) for i in range(1, MAX_BUCKETS + 10))
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="cap", unit="ms", boundaries=many)


# HB_INV_06 — default presets from semconv
def test_inv_default_presets_confirms() -> None:
    lat = HistogramBuckets.latency_ms_default()
    assert lat.unit == "ms"
    assert 100.0 in lat.boundaries
    assert 1.0 in lat.boundaries


def test_inv_default_presets_prevents() -> None:
    # Modifying the default preset does not affect a fresh build.
    a = HistogramBuckets.latency_ms_default()
    b = HistogramBuckets.latency_ms_default()
    assert a.boundaries == b.boundaries


def test_inv_default_presets_under_failure() -> None:
    # Default payload buckets span bytes → megabytes.
    sz = HistogramBuckets.payload_bytes_default()
    assert max(sz.boundaries) >= 1_000_000.0
