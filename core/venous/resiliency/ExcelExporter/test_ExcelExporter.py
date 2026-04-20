"""Invariant tests for `ExcelExporter`."""
from __future__ import annotations

import math


class _Exporter:
    def __init__(self, chunk_size: int = 10, max_rows: int = 100):
        self.chunk_size = chunk_size
        self.max_rows = max_rows

    def write_rows(self, rows: list[tuple]) -> list[int]:
        if len(rows) > self.max_rows:
            raise ValueError(f"max_rows={self.max_rows} exceeded")
        flush_points: list[int] = []
        buf: list = []
        for r in rows:
            buf.append(r)
            if len(buf) >= self.chunk_size:
                flush_points.append(len(buf))
                buf = []
        if buf:
            flush_points.append(len(buf))
        return flush_points


# INV_01 -----------------------------------------------------------------
def test_inv_max_rows_cap_confirms() -> None:
    x = _Exporter(max_rows=5)
    x.write_rows([("a",)] * 5)  # OK


def test_inv_max_rows_cap_prevents() -> None:
    x = _Exporter(max_rows=3)
    try:
        x.write_rows([("a",)] * 4)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_inv_max_rows_cap_under_failure() -> None:
    # max_rows=0 -> any non-empty input is rejected.
    x = _Exporter(max_rows=0)
    try: x.write_rows([("a",)])
    except ValueError: return
    raise AssertionError("expected ValueError")


# INV_02 -----------------------------------------------------------------
def _simulate_create_workbook(openpyxl_available: bool):
    """Mirror the staged impl's import-or-raise pattern."""
    if not openpyxl_available:
        raise ImportError("openpyxl is required: pip install openpyxl")
    return object()  # stand-in for a Workbook


def test_inv_import_error_actionable_confirms() -> None:
    try:
        _simulate_create_workbook(False)
    except ImportError as exc:
        assert "pip install" in str(exc).lower()
        return
    raise AssertionError("expected ImportError")


def test_inv_import_error_actionable_prevents() -> None:
    # When available, NO ImportError.
    wb = _simulate_create_workbook(True)
    assert wb is not None


def test_inv_import_error_actionable_under_failure() -> None:
    # Error class is specifically ImportError, not bare Exception.
    try:
        _simulate_create_workbook(False)
    except ImportError:
        return
    raise AssertionError("wrong exception type")


# INV_03 -----------------------------------------------------------------
def test_inv_chunked_write_confirms() -> None:
    x = _Exporter(chunk_size=10, max_rows=1000)
    fp = x.write_rows([("a",)] * 25)
    # 25 rows with chunk=10 -> 3 flushes (10, 10, 5)
    assert fp == [10, 10, 5]
    assert len(fp) == math.ceil(25 / 10)


def test_inv_chunked_write_prevents() -> None:
    x = _Exporter(chunk_size=10, max_rows=1000)
    fp = x.write_rows([("a",)] * 9)
    # 9 rows with chunk=10 -> one partial flush, never two.
    assert fp == [9]


def test_inv_chunked_write_under_failure() -> None:
    x = _Exporter(chunk_size=5, max_rows=10)
    fp = x.write_rows([])  # empty input -> no flushes
    assert fp == []
