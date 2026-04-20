"""Unit tests for TamperEvidentAuditLog: 3 tests per invariant."""

from __future__ import annotations

import pytest

from TamperEvidentAuditLog import (
    GENESIS_PREV_HASH,
    HmacReferenceSigner,
    InMemoryTamperEvidentAuditLog,
    TamperEvidentAuditLogError,
    _canonical_bytes,
    _compute_entry_hash,
)


def _log() -> InMemoryTamperEvidentAuditLog:
    return InMemoryTamperEvidentAuditLog(HmacReferenceSigner(b"x" * 32, "kid-test"))


# TEAL_INV_01 — append-only
def test_inv_append_only_confirms() -> None:
    log = _log()
    log.append("alice", "CREATE", "res:1", "success", {})
    assert log.size == 1


def test_inv_append_only_prevents() -> None:
    log = _log()
    # No mutating surface is exposed.
    for attr in ("delete", "update", "remove", "pop", "truncate", "clear"):
        assert not hasattr(log, attr)


def test_inv_append_only_under_failure() -> None:
    log = _log()
    for i in range(20):
        log.append("svc", "READ", f"res:{i}", "success", {})
    # After ten appends, size reflects every one; none was dropped.
    assert log.size == 20


# TEAL_INV_02 — hash chain links
def test_inv_hash_chain_confirms() -> None:
    log = _log()
    log.append("a", "READ", "r1", "success", {})
    log.append("a", "READ", "r2", "success", {})
    assert log.verify_chain() is True


def test_inv_hash_chain_prevents() -> None:
    log = _log()
    log.append("a", "READ", "r1", "success", {})
    log.append("a", "READ", "r2", "success", {})
    # Simulate storage tamper: mutate a stored entry's actor (private attr).
    first = log._entries[0]
    from dataclasses import replace
    log._entries[0] = replace(first, actor="MALLORY")
    assert log.verify_chain() is False


def test_inv_hash_chain_under_failure() -> None:
    log = _log()
    log.append("a", "READ", "r1", "success", {})
    log.append("a", "READ", "r2", "success", {})
    # Break a link: overwrite prev_hash of seq=2.
    from dataclasses import replace
    log._entries[1] = replace(log._entries[1], prev_hash="bad" * 21 + "b")
    assert log.verify_chain() is False


# TEAL_INV_03 — signer is external
def test_inv_signer_external_confirms() -> None:
    log = _log()
    log.append("a", "CREATE", "r", "success", {"k": "v"})
    entry = log.get(1)
    assert entry["signature"] and entry["key_id"] == "kid-test"


def test_inv_signer_external_prevents() -> None:
    # The signer Protocol requires sign/verify/key_id; building without one raises.
    with pytest.raises(TamperEvidentAuditLogError):
        InMemoryTamperEvidentAuditLog(signer=object())  # type: ignore[arg-type]


def test_inv_signer_external_under_failure() -> None:
    # Cross-signer verification fails: a log's signature verifies with its own signer
    # but NOT with an independently-seeded signer.
    s1 = HmacReferenceSigner(b"a" * 32, "k1")
    s2 = HmacReferenceSigner(b"b" * 32, "k2")
    log = InMemoryTamperEvidentAuditLog(s1)
    log.append("x", "READ", "r", "success", {})
    # Swap signer and re-verify.
    log._signer = s2
    assert log.verify_chain() is False


# TEAL_INV_04 — monotonic sequence
def test_inv_monotonic_seq_confirms() -> None:
    log = _log()
    for i in range(5):
        log.append("a", "READ", f"r{i}", "success", {})
    for i, seq in enumerate(range(1, 6)):
        assert log.get(seq)["seq"] == seq


def test_inv_monotonic_seq_prevents() -> None:
    log = _log()
    with pytest.raises(TamperEvidentAuditLogError):
        log.get(0)
    with pytest.raises(TamperEvidentAuditLogError):
        log.get(1)  # empty log


def test_inv_monotonic_seq_under_failure() -> None:
    log = _log()
    for i in range(3):
        log.append("a", "READ", f"r{i}", "success", {})
    # Delete the middle entry to create a gap (simulated tamper).
    del log._entries[1]
    assert log.verify_chain() is False


# TEAL_INV_05 — mandatory fields
def test_inv_required_fields_confirms() -> None:
    log = _log()
    log.append("a", "CREATE", "r", "success", {})
    log.append("a", "READ", "r", "failure", {"k": "v"})
    log.append("a", "DELETE", "r", "denied", {})


def test_inv_required_fields_prevents() -> None:
    log = _log()
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("", "CREATE", "r", "success", {})
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("a", "", "r", "success", {})
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("a", "CREATE", "", "success", {})
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("a", "CREATE", "r", "INVALID", {})
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("a", "CREATE", "r", "success", "not-a-mapping")  # type: ignore[arg-type]


def test_inv_required_fields_under_failure() -> None:
    log = _log()
    # Whitespace-only actor is also rejected — TEAL_INV_05 is strict.
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("   ", "CREATE", "r", "success", {})


# TEAL_INV_06 — server-side timestamp
def test_inv_server_timestamp_confirms() -> None:
    log = _log()
    log.append("a", "READ", "r", "success", {})
    entry = log.get(1)
    assert "timestamp" in entry and entry["timestamp"].endswith("+00:00")


def test_inv_server_timestamp_prevents() -> None:
    # The Protocol does not allow client-supplied timestamps — the signature's
    # only positional args are actor/action/resource/outcome/attributes.
    log = _log()
    import inspect
    sig = inspect.signature(log.append)
    assert "timestamp" not in sig.parameters and "ts" not in sig.parameters


def test_inv_server_timestamp_under_failure() -> None:
    # Two rapid appends must have non-decreasing timestamps (monotonic clock).
    log = _log()
    log.append("a", "READ", "r1", "success", {})
    log.append("a", "READ", "r2", "success", {})
    t1 = log.get(1)["timestamp"]
    t2 = log.get(2)["timestamp"]
    assert t1 <= t2


# Extra: canonical serialisation is deterministic across attribute insertion order.
def test_canonical_bytes_order_insensitive() -> None:
    from datetime import datetime, timezone
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    b1 = _canonical_bytes(seq=1, timestamp=ts, actor="a", action="READ",
                          resource="r", outcome="success",
                          attributes={"x": 1, "y": 2}, prev_hash=GENESIS_PREV_HASH)
    b2 = _canonical_bytes(seq=1, timestamp=ts, actor="a", action="READ",
                          resource="r", outcome="success",
                          attributes={"y": 2, "x": 1}, prev_hash=GENESIS_PREV_HASH)
    assert b1 == b2
    assert _compute_entry_hash(b1) == _compute_entry_hash(b2)
