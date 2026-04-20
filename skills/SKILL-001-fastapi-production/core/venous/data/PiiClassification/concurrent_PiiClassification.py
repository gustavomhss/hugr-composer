"""Concurrency tests: linearisability of registration under threads."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PiiClassification import InMemoryPiiClassification, PiiClass


@dataclass
class U:
    f: str


def test_concurrent_registration_final_consistent() -> None:
    c = InMemoryPiiClassification()

    def worker(i: int) -> None:
        # All threads register at the SAME (upward) rank — one of them must win,
        # and classify() must return a member of the concurrent set.
        c.register(U, "f", PiiClass.PII)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.classify(U, "f") is PiiClass.PII


def test_concurrent_leak_counter_monotonic() -> None:
    c = InMemoryPiiClassification()

    def worker() -> None:
        c.audit_leak(object(), sink="s")

    threads = [threading.Thread(target=worker) for _ in range(80)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.leak_count == 80
