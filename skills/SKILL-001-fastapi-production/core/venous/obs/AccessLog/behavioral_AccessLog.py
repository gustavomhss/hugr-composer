"""Behavioral scenarios for AccessLog."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from AccessLog import AccessLogError, InMemoryAccessLog


UTC = timezone.utc


def test_scenario_hipaa_accounting_of_disclosures() -> None:
    log = InMemoryAccessLog()
    for i in range(3):
        log.record_read(f"dr-{i}", "phi:patient:42", "phi", "treatment",
                        datetime(2026, 1, i + 1, tzinfo=UTC))
    rows = log.query(record_id="phi:patient:42")
    assert len(rows) == 3


def test_scenario_per_actor_rate() -> None:
    log = InMemoryAccessLog()
    t = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(10):
        log.record_read("dr-1", "r", "phi", "treatment", t)
    n = log.count_by_actor("dr-1", since=t - timedelta(seconds=1))
    assert n == 10


def test_scenario_retention_enforced() -> None:
    log = InMemoryAccessLog(retention=timedelta(days=1))
    log.record_read("dr-1", "r", "phi", "treatment",
                    datetime(2026, 1, 1, tzinfo=UTC))
    dropped = log.sweep_retention(now=datetime(2026, 1, 3, tzinfo=UTC))
    assert dropped == 1 and log.size == 0


def test_scenario_purpose_validation_protects_queries() -> None:
    log = InMemoryAccessLog()
    with pytest.raises(AccessLogError):
        log.record_read("dr-1", "r", "phi", "marketing",
                        datetime(2026, 1, 1, tzinfo=UTC))


def test_scenario_query_filter_by_actor() -> None:
    log = InMemoryAccessLog()
    t = datetime(2026, 1, 1, tzinfo=UTC)
    log.record_read("dr-1", "r1", "phi", "treatment", t)
    log.record_read("dr-2", "r2", "phi", "treatment", t)
    assert len(log.query(actor="dr-1")) == 1
