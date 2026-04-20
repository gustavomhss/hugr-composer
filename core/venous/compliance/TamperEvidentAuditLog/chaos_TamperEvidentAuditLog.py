"""Chaos + game-day tests: concurrency, tamper, amplification."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from TamperEvidentAuditLog import (
    HmacReferenceSigner,
    InMemoryTamperEvidentAuditLog,
    TamperEvidentAuditLogError,
)


def _log() -> InMemoryTamperEvidentAuditLog:
    return InMemoryTamperEvidentAuditLog(HmacReferenceSigner(b"c" * 32, "chaos-kid"))


def test_chaos_concurrent_appends_preserve_chain() -> None:
    log = _log()

    def worker(i: int) -> None:
        log.append(f"actor-{i}", "READ", f"res:{i}", "success", {"tid": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert log.size == 30
    assert log.verify_chain() is True
    # Sequence numbers MUST be 1..30 with no duplicates or gaps.
    seqs = [log.get(i)["seq"] for i in range(1, 31)]
    assert seqs == list(range(1, 31))


def test_chaos_tamper_detected_on_any_field() -> None:
    log = _log()
    log.append("a", "READ", "r", "success", {"k": "v"})
    # Try tampering every scalar; verification must catch it.
    for field, value in (
        ("actor", "mallory"),
        ("action", "MODIFIED"),
        ("resource", "x"),
        ("outcome", "denied"),
    ):
        saved = log._entries[0]
        log._entries[0] = replace(saved, **{field: value})
        assert log.verify_chain() is False, f"tamper on {field} undetected"
        log._entries[0] = saved  # restore for next loop iteration


def test_chaos_gap_injection_detected() -> None:
    log = _log()
    for i in range(5):
        log.append("a", "READ", f"r{i}", "success", {})
    # Drop seq=3.
    del log._entries[2]
    assert log.verify_chain() is False


def test_chaos_large_attributes_accepted() -> None:
    log = _log()
    big = {f"k{i}": "v" * 100 for i in range(50)}
    log.append("a", "READ", "r", "success", big)
    assert log.verify_chain() is True


def test_chaos_invalid_inputs_rejected_repeatedly() -> None:
    log = _log()
    for bad_outcome in ("ok", "partial", "", "SUCCESS", "Success"):
        with pytest.raises(TamperEvidentAuditLogError):
            log.append("a", "READ", "r", bad_outcome, {})


def test_chaos_verify_chain_out_of_range_fails_gracefully() -> None:
    log = _log()
    log.append("a", "READ", "r", "success", {})
    assert log.verify_chain(start_seq=5, end_seq=10) is False
    assert log.verify_chain(start_seq=0, end_seq=1) is False
    assert log.verify_chain(start_seq=2, end_seq=1) is False
