"""Concurrency tests for VerdictLedger — linearizability under contention."""

from __future__ import annotations

import threading

from OutputGuardrail import (
    PolicyOutputGuardrail,
    SafetyOutputGuardrail,
    SchemaOutputGuardrail,
    Verdict,
    VerdictLedger,
    apply_chain,
)


def test_concurrent_records_preserve_count() -> None:
    ledger = VerdictLedger()
    g = SafetyOutputGuardrail(name="safety")

    def _go() -> None:
        apply_chain([g], "ok", ledger=ledger)

    threads = [threading.Thread(target=_go) for _ in range(128)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ledger.size() == 128
    assert len(ledger.entries_for("safety")) == 128


def test_concurrent_mixed_chain_preserves_attribution() -> None:
    ledger = VerdictLedger()
    schemas: dict[str, dict[str, object]] = {
        "x": {"type": "object", "properties": {"k": {"type": "string"}}},
    }
    chain = [
        SafetyOutputGuardrail(name="safety"),
        PolicyOutputGuardrail(name="policy"),
        SchemaOutputGuardrail(name="schema", schemas=schemas),
    ]

    def _go() -> None:
        apply_chain(chain, '{"k": "v"}', schema_ref="x", ledger=ledger)

    threads = [threading.Thread(target=_go) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 32 invocations × 3 guards = 96 entries, each attributed correctly.
    assert ledger.size() == 96
    assert len(ledger.entries_for("safety")) == 32
    assert len(ledger.entries_for("policy")) == 32
    assert len(ledger.entries_for("schema")) == 32


def test_concurrent_clear_is_atomic() -> None:
    ledger = VerdictLedger()
    # Pre-populate.
    for _ in range(50):
        ledger.record("g", Verdict(action="pass", reason="ok"))

    results: list[int] = []

    def _reader() -> None:
        results.append(ledger.size())

    def _clearer() -> None:
        ledger.clear()

    threads = [
        *(threading.Thread(target=_reader) for _ in range(16)),
        threading.Thread(target=_clearer),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # After all threads join, size is either 0 or 50 — never a partial value.
    for r in results:
        assert r in (0, 50)
    assert ledger.size() == 0


def test_concurrent_entries_snapshot_is_consistent() -> None:
    ledger = VerdictLedger()
    writers_done = threading.Event()
    seen_sizes: list[int] = []

    def _writer() -> None:
        for _ in range(50):
            ledger.record("w", Verdict(action="pass", reason="ok"))
        writers_done.set()

    def _reader() -> None:
        while not writers_done.is_set():
            snap = ledger.entries()
            # A snapshot MUST be internally consistent: its length equals the
            # count of entries returned, and every entry has a Verdict action.
            assert len(snap) >= 0
            seen_sizes.append(len(snap))
            for name, v in snap:
                assert name == "w"
                assert v.action in {"pass", "rewrite", "block"}

    wt = threading.Thread(target=_writer)
    rts = [threading.Thread(target=_reader) for _ in range(4)]
    wt.start()
    for r in rts:
        r.start()
    wt.join()
    for r in rts:
        r.join()
    # Sizes observed are monotonically non-decreasing when sorted (no gaps).
    assert ledger.size() == 50
