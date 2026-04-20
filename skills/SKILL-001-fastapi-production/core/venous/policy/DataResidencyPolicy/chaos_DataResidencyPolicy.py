"""Chaos tests for DataResidencyPolicy."""

from __future__ import annotations

import threading

import pytest

from DataResidencyPolicy import (
    DataResidencyPolicy,
    DataResidencyPolicyError,
    InMemoryResidencyEnforcer,
)


def _p(**o: object) -> DataResidencyPolicy:
    base: dict[str, object] = {
        "data_class": "x", "allowed_regions": ("DE",),
        "transfer_mechanism": "SCC_2021/914",
    }
    base.update(o)
    return DataResidencyPolicy(**base)  # type: ignore[arg-type]


def test_chaos_concurrent_binds() -> None:
    e = InMemoryResidencyEnforcer()

    def worker(i: int) -> None:
        e.bind(_p(data_class=f"dc-{i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert e.size == 30


def test_chaos_junk_regions_rejected_many() -> None:
    for bad in ("us", "USA", "d3", "", "DE "):
        with pytest.raises(DataResidencyPolicyError):
            _p(allowed_regions=(bad,))


def test_chaos_empty_allowed_regions_rejected() -> None:
    with pytest.raises(DataResidencyPolicyError):
        _p(allowed_regions=())


def test_chaos_junk_mechanism_rejected() -> None:
    for bad in ("ssh-handshake", "", "SCC"):
        with pytest.raises(DataResidencyPolicyError):
            _p(transfer_mechanism=bad)


def test_chaos_check_write_repeatedly_deterministic() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(_p())
    for _ in range(20):
        e.check_write("x", "DE")
