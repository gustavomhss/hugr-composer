"""Metamorphic + differential tests for TamperEvidentAuditLog."""

from __future__ import annotations

from TamperEvidentAuditLog import (
    HmacReferenceSigner,
    InMemoryTamperEvidentAuditLog,
    _canonical_bytes,
    _compute_entry_hash,
)


def _log() -> InMemoryTamperEvidentAuditLog:
    return InMemoryTamperEvidentAuditLog(HmacReferenceSigner(b"z" * 32, "kid-meta"))


def test_metamorphic_attributes_order_invariant() -> None:
    from datetime import datetime, timezone
    ts = datetime(2026, 2, 2, tzinfo=timezone.utc)
    h1 = _compute_entry_hash(_canonical_bytes(
        seq=1, timestamp=ts, actor="a", action="R", resource="r",
        outcome="success", attributes={"a": 1, "b": 2}, prev_hash="0" * 64,
    ))
    h2 = _compute_entry_hash(_canonical_bytes(
        seq=1, timestamp=ts, actor="a", action="R", resource="r",
        outcome="success", attributes={"b": 2, "a": 1}, prev_hash="0" * 64,
    ))
    assert h1 == h2


def test_metamorphic_chain_extension_preserves_prefix_verify() -> None:
    log = _log()
    log.append("a", "READ", "r1", "success", {})
    log.append("a", "READ", "r2", "success", {})
    # Snapshot the first two entries' hashes.
    h_snapshot = [e.entry_hash for e in log._entries]
    log.append("a", "READ", "r3", "success", {})
    assert log.verify_chain(start_seq=1, end_seq=2) is True
    # Original prefix hashes are unchanged (append-only).
    assert [e.entry_hash for e in log._entries[:2]] == h_snapshot


def test_metamorphic_single_field_change_flips_hash() -> None:
    log = _log()
    h1 = log.append("a", "READ", "r", "success", {})
    # A new log with ANY field changed yields a different hash.
    log2 = _log()
    h2 = log2.append("b", "READ", "r", "success", {})  # different actor
    assert h1 != h2


def test_differential_export_reparse_hash_stable() -> None:
    import json
    log = _log()
    for i in range(3):
        log.append("a", "READ", f"r{i}", "success", {"i": i})
    blob = log.export(since_seq=1)
    rows = [json.loads(line) for line in blob.decode().splitlines()]
    # For every row, the stored entry_hash matches a re-computation from its
    # canonical payload — the off-box verifier reproduces the writer's digest.
    for row in rows:
        from datetime import datetime
        payload = _canonical_bytes(
            seq=row["seq"], timestamp=datetime.fromisoformat(row["timestamp"]),
            actor=row["actor"], action=row["action"], resource=row["resource"],
            outcome=row["outcome"], attributes=row["attributes"],
            prev_hash=row["prev_hash"],
        )
        assert _compute_entry_hash(payload) == row["entry_hash"]


def test_metamorphic_empty_log_verifies_true() -> None:
    log = _log()
    assert log.verify_chain() is True


def test_metamorphic_idempotent_verify_calls() -> None:
    log = _log()
    for i in range(5):
        log.append("a", "READ", f"r{i}", "success", {})
    # Verification is a pure query: many calls give the same answer.
    results = [log.verify_chain() for _ in range(10)]
    assert all(results)
