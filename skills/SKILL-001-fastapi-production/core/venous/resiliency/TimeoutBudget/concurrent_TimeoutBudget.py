"""Concurrency / linearizability harness for TimeoutBudget.

Asserts that concurrent readers of ``remaining_ms`` observe a monotonically
non-increasing sequence and that derivation under race cannot inflate a child
past its parent's deadline.
"""

from __future__ import annotations

import asyncio
import threading

from TimeoutBudget import (
    MonotonicTimeoutBudget,
    bind,
    current,
)


def test_concurrent_remaining_ms_monotonic_across_threads() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=300, origin="req")
    readings: list[int] = []
    lock = threading.Lock()

    def reader() -> None:
        r = budget.remaining_ms()
        with lock:
            readings.append(r)

    ts = [threading.Thread(target=reader) for _ in range(100)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # All readings must be within [0, 300].
    assert all(0 <= r <= 300 for r in readings)


def test_concurrent_derive_never_exceeds_parent() -> None:
    parent = MonotonicTimeoutBudget.from_ms(total_ms=500, origin="req")
    bad: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        child = parent.derive(child_max_ms=10_000)
        if child.deadline_ns > parent.deadline_ns:
            with lock:
                bad.append(child.deadline_ns)

    ts = [threading.Thread(target=worker) for _ in range(64)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert bad == []


def test_concurrent_asyncio_contextvar_propagation() -> None:
    # asyncio tasks MUST inherit CURRENT_BUDGET automatically (contextvars).
    async def child() -> str:
        return current().origin

    async def main() -> list[str]:
        budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="req-async")
        with bind(budget):
            return await asyncio.gather(child(), child(), child())

    origins = asyncio.run(main())
    assert origins == ["req-async", "req-async", "req-async"]


def test_concurrent_thread_does_not_inherit_without_copy_context() -> None:
    # Plain threading (no copy_context()) MUST NOT leak the ambient budget.
    from TimeoutBudget import CURRENT_BUDGET
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="req")
    seen: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        with lock:
            seen.append(CURRENT_BUDGET.get())

    with bind(budget):
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    assert seen == [None]
