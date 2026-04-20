"""Metamorphic tests for AccessLog."""

from __future__ import annotations

from datetime import datetime, timezone

from AccessLog import InMemoryAccessLog


UTC = timezone.utc
T = datetime(2026, 1, 1, tzinfo=UTC)


def test_metamorphic_query_monotone_in_filters() -> None:
    log = InMemoryAccessLog()
    log.record_read("dr-1", "r1", "phi", "treatment", T)
    log.record_read("dr-2", "r1", "phi", "treatment", T)
    all_rows = log.query(record_id="r1")
    by_actor = log.query(record_id="r1", actor="dr-1")
    assert len(by_actor) <= len(all_rows)


def test_metamorphic_count_matches_query_length() -> None:
    log = InMemoryAccessLog()
    for i in range(5):
        log.record_read("dr-1", f"r:{i}", "phi", "treatment", T)
    assert log.count_by_actor("dr-1", since=T) == len(log.query(actor="dr-1"))


def test_metamorphic_order_preserved() -> None:
    log = InMemoryAccessLog()
    for i in range(5):
        log.record_read(f"a{i}", f"r{i}", "phi", "treatment", T)
    rows = log.query()
    assert [r["actor"] for r in rows] == [f"a{i}" for i in range(5)]


def test_differential_audit_vs_access_storage() -> None:
    log = InMemoryAccessLog()
    for _ in range(3):
        log.record_read("dr-1", "r", "phi", "treatment", T)
    # Query does not return hash-chain fields.
    rows = log.query()
    assert all("entry_hash" not in r for r in rows)


def test_metamorphic_empty_query_returns_all() -> None:
    log = InMemoryAccessLog()
    log.record_read("a", "r", "phi", "audit", T)
    assert log.query() == log.query(record_id=None, actor=None)
