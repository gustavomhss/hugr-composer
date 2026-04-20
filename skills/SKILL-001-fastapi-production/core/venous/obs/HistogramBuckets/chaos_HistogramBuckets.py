"""Chaos tests for HistogramBuckets."""

from __future__ import annotations

import pytest

from HistogramBuckets import HistogramBuckets, HistogramBucketsInvariantError


def test_chaos_nan_boundary_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="x", unit="ms", boundaries=(float("nan"), 1.0))


def test_chaos_inf_boundary_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="x", unit="ms", boundaries=(1.0, float("inf")))


def test_chaos_duplicate_boundaries_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="x", unit="ms", boundaries=(1.0, 1.0, 2.0))


def test_chaos_descending_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="x", unit="ms", boundaries=(10.0, 5.0, 1.0))


def test_chaos_empty_boundaries_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="x", unit="ms", boundaries=())


def test_chaos_bool_boundary_rejected() -> None:
    with pytest.raises(HistogramBucketsInvariantError):
        HistogramBuckets(name="x", unit="ms", boundaries=(True, 5.0))  # type: ignore[arg-type]
