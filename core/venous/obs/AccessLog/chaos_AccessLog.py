"""Chaos tests for AccessLog."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from AccessLog import AccessLogError, InMemoryAccessLog


UTC = timezone.utc
T = datetime(2026, 1, 1, tzinfo=UTC)


def test_chaos_concurrent_reads_counted() -> None:
    log = InMemoryAccessLog()

    def worker(i: int) -> None:
        log.record_read(f"dr-{i}", "r", "phi", "treatment", T)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert log.size == 40


def test_chaos_invalid_purpose_rejected_repeatedly() -> None:
    log = InMemoryAccessLog()
    for bad in ("marketing", "", "TREATMENT", "treatment "):
        with pytest.raises(AccessLogError):
            log.record_read("dr-1", "r", "phi", bad, T)


def test_chaos_bare_system_actor_rejected() -> None:
    log = InMemoryAccessLog()
    with pytest.raises(AccessLogError):
        log.record_read("system", "r", "phi", "audit", T)


def test_chaos_retention_sweep_idempotent() -> None:
    log = InMemoryAccessLog()
    log.record_read("dr-1", "r", "phi", "treatment", T)
    from datetime import timedelta
    log.sweep_retention(now=T + timedelta(days=365))
    # Second call yields zero; idempotent.
    assert log.sweep_retention(now=T + timedelta(days=365)) == 0


def test_chaos_large_burst_tolerated() -> None:
    log = InMemoryAccessLog()
    for i in range(500):
        log.record_read("dr-1", f"r:{i}", "phi", "treatment", T)
    assert log.size == 500
