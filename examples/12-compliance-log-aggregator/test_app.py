"""Tests for the compliance log aggregator example."""
from __future__ import annotations

import dataclasses

import pytest

from app import LogStore


DAY = 86400.0


def test_credit_card_masked_and_tagged_pci() -> None:
    store = LogStore()
    e = store.ingest("api", timestamp=0.0,
                     fields={"msg": "card 4111 1111 1111 1111 charged"})
    assert e.sensitivity == "pci"
    assert "4111" not in str(e.fields)
    assert "MASKED" in str(e.fields)


def test_deleting_an_entry_breaks_chain_verification() -> None:
    store = LogStore()
    store.ingest("api", timestamp=0.0, fields={"msg": "hello"})
    store.ingest("api", timestamp=1.0, fields={"msg": "world"})
    store.ingest("api", timestamp=2.0, fields={"msg": "again"})
    assert store.verify() is True

    entries = store.entries()
    tampered = [entries[0], entries[2]]  # dropped index 1
    assert store.verify(tampered) is False


def test_day_91_dry_run_flags_general_skips_pci() -> None:
    store = LogStore()
    # Day 0 — both a general and a PCI event.
    store.ingest("api", timestamp=0.0, fields={"msg": "plain text"})
    store.ingest("api", timestamp=0.0, fields={"card": "4111 1111 1111 1111"})
    # Day 91 dry-run: general TTL = 90d, PII/PCI TTL = 7y (2555d).
    eligible = store.retention_dry_run(
        now=91 * DAY, general_ttl_s=90 * DAY, pii_ttl_s=2555 * DAY,
    )
    assert eligible == [0]  # only the general event


def test_same_query_twice_returns_same_dataset() -> None:
    store = LogStore()
    for i in range(5):
        store.ingest("api", timestamp=float(i), fields={"i": str(i)})
    r1 = store.query("auditor-A", t_from=0.0, t_to=10.0)
    r2 = store.query("auditor-B", t_from=0.0, t_to=10.0)
    assert r1 == r2
    # Both queries were audited.
    log = store.access_log()
    assert log == [("auditor-A", 0.0, 10.0), ("auditor-B", 0.0, 10.0)]


def test_tampering_with_content_breaks_chain() -> None:
    store = LogStore()
    store.ingest("api", timestamp=0.0, fields={"msg": "first"})
    store.ingest("api", timestamp=1.0, fields={"msg": "second"})
    entries = store.entries()
    tampered = [
        dataclasses.replace(entries[0], fields={"msg": "ALTERED"}),
        entries[1],
    ]
    assert store.verify(tampered) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
