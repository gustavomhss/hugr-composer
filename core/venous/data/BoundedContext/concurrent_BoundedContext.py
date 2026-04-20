"""Concurrency / linearizability harness for BoundedContext.

Confirms that concurrent claim attempts, language mutations, and context-map
publications remain race-free: the ledger admits exactly one owner per
aggregate type, language conflicts never corrupt state, and the context map
returns consistent readings to concurrent observers.
"""

from __future__ import annotations

import threading

from BoundedContext import (
    REL_OPEN_HOST,
    REL_PARTNERSHIP,
    ContextMap,
    SharedOwnershipError,
    SimpleBoundedContext,
    UbiquitousLanguageConflictError,
    _OwnershipLedger,
)


class _Order:
    pass


def test_concurrent_claims_have_exactly_one_winner() -> None:
    ledger = _OwnershipLedger()
    contexts = [SimpleBoundedContext(f"ctx-{i}", ledger=ledger) for i in range(32)]
    winners: list[str] = []
    lock = threading.Lock()

    def worker(ctx: SimpleBoundedContext) -> None:
        try:
            ctx.claim(_Order)
            with lock:
                winners.append(ctx.name)
        except SharedOwnershipError:
            return

    ts = [threading.Thread(target=worker, args=(c,)) for c in contexts]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(winners) == 1
    assert ledger.owner_of(_Order) == winners[0]


def test_concurrent_language_conflicts_never_corrupt_state() -> None:
    ctx = SimpleBoundedContext("a")
    ctx.define_term("order", "legit")
    errors: list[BaseException] = []
    conflicts: list[int] = []
    lock = threading.Lock()

    def worker(meaning: str) -> None:
        try:
            ctx.define_term("order", meaning)
        except UbiquitousLanguageConflictError:
            with lock:
                conflicts.append(1)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(f"attacker-{i}",)) for i in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert len(conflicts) == 50
    assert ctx.language["order"] == "legit"


def test_concurrent_context_map_reads_are_consistent() -> None:
    cmap = ContextMap()
    cmap.add_relationship("sales", "billing", REL_PARTNERSHIP)
    seen: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        kind = cmap.relationship("sales", "billing")
        with lock:
            seen.append(kind)

    ts = [threading.Thread(target=reader) for _ in range(64)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(seen) == 64
    assert all(k == REL_PARTNERSHIP for k in seen)


def test_concurrent_publish_adds_many_edges_without_loss() -> None:
    cmap = ContextMap()

    def writer(i: int) -> None:
        cmap.add_relationship(f"u{i}", f"d{i}", REL_OPEN_HOST)

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(200)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    integrations = list(cmap.integrations())
    assert len(integrations) == 200
    assert {k for _u, _d, k in integrations} == {REL_OPEN_HOST}
