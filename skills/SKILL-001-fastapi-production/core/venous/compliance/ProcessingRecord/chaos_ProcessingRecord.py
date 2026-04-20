"""Chaos tests for ProcessingRecord."""

from __future__ import annotations

import threading

import pytest

from ProcessingRecord import (
    InMemoryProcessingRegistry,
    ProcessingRecord,
    ProcessingRecordError,
)


def _r(**o: object) -> ProcessingRecord:
    base: dict[str, object] = {
        "activity": "a", "controller": "c", "purposes": ("p",),
        "data_classes": ("pii",), "recipients": ("i",),
        "retention_ref": "r", "legal_basis": "GDPR Art 6(1)(a) consent",
    }
    base.update(o)
    return ProcessingRecord(**base)  # type: ignore[arg-type]


def test_chaos_concurrent_register() -> None:
    r = InMemoryProcessingRegistry()

    def worker(i: int) -> None:
        r.register(_r(activity=f"a{i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert r.size == 30


def test_chaos_invalid_country_rejected_many_times() -> None:
    for bad in ("USA", "us", "", "us1", "u"):
        with pytest.raises(ProcessingRecordError):
            _r(transfers_outside_eea=(bad,))


def test_chaos_empty_purposes_rejected() -> None:
    with pytest.raises(ProcessingRecordError):
        _r(purposes=())


def test_chaos_export_large_registry() -> None:
    r = InMemoryProcessingRegistry()
    for i in range(200):
        r.register(_r(activity=f"a{i}"))
    payload = r.export_ropa()
    assert payload.startswith(b"[") and payload.endswith(b"]")


def test_chaos_freetext_basis_rejected() -> None:
    with pytest.raises(ProcessingRecordError):
        _r(legal_basis="convenient")
