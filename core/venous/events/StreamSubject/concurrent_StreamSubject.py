"""Concurrency tests for StreamSubject + SubjectRegistry."""

from __future__ import annotations

import threading

from StreamSubject import StreamSubject, SubjectRegistry


def test_concurrent_subscribe_publish_count_consistent() -> None:
    reg = SubjectRegistry()
    def subscribe(n: int) -> None:
        for i in range(n):
            reg.subscribe("a.>", f"c-{threading.get_ident()}-{i}")
    threads = [threading.Thread(target=subscribe, args=(50,)) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    # 8 threads × 50 subscribers = 400. A publish visits every subscriber.
    count = reg.publish(StreamSubject("a.b.c"))
    assert count == 400


def test_concurrent_publish_ordering_stable_per_sequence() -> None:
    reg = SubjectRegistry()
    reg.subscribe("a.>", "c1")
    # Many threads publishing concurrently; deliveries should preserve seq order per thread.
    def publish_all() -> None:
        for i in range(20):
            reg.publish(StreamSubject(f"a.b.{i}"))
    threads = [threading.Thread(target=publish_all) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    deliveries = reg.deliveries()
    seqs = [d[2] for d in deliveries]
    # Sequence numbers are strictly monotonic per the registry lock.
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_concurrent_unsubscribe_safe() -> None:
    reg = SubjectRegistry()
    for i in range(200):
        reg.subscribe("a.>", f"c{i}")
    def unsubscribe_many() -> None:
        for i in range(100):
            reg.unsubscribe("a.>", f"c{i}")
    threads = [threading.Thread(target=unsubscribe_many) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    # Some subscribers still present (the non-overlapping half).
    count = reg.publish(StreamSubject("a.b"))
    assert count == 100
