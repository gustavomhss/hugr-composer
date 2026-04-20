"""Concurrency / linearizability harness for Specification.

Proves that the TranslatorRegistry (the only mutable shared state) stays
linearizable under concurrent reads/writes and that pure-predicate
composition is trivially safe to share across threads (SPEC-INV-01).
"""

from __future__ import annotations

import threading

from Specification import (
    PredicateSpecification,
    TranslatorRegistry,
    in_memory_filter,
)


def test_concurrent_registry_register_and_translate() -> None:
    reg = TranslatorRegistry()
    errors: list[BaseException] = []
    lock = threading.Lock()

    # Pre-register a baseline leaf so readers always have something to find.
    reg.register("sql", "ready", lambda s: "1=1")

    def writer() -> None:
        try:
            for i in range(200):
                reg.register("sql", f"w_{i}", lambda s, i=i: f"x = {i}")
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def reader() -> None:
        try:
            spec = PredicateSpecification[int]("ready", lambda x: True)
            for _ in range(500):
                out = reg.translate("sql", spec)
                assert out == "1=1"
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # All writer registrations survived.
    for i in range(200):
        spec = PredicateSpecification[int](f"w_{i}", lambda x: True)
        assert reg.translate("sql", spec) == f"x = {i}"


def test_concurrent_pure_predicate_shared_across_threads() -> None:
    # SPEC-INV-01: a pure Specification MUST be safe to evaluate concurrently
    # on many candidates without synchronization.
    spec = PredicateSpecification[int]("pos_and_even", lambda x: x > 0 and x % 2 == 0)
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        out = in_memory_filter(spec, range(-100, 101))
        with lock:
            results.extend(out)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = [x for x in range(-100, 101) if x > 0 and x % 2 == 0]
    # 20 threads, each producing identical output → 20 * len(expected) items.
    assert len(results) == 20 * len(expected)
    # Every chunk of len(expected) matches exactly — no torn reads.
    for i in range(20):
        chunk = results[i * len(expected):(i + 1) * len(expected)]
        assert chunk == expected


def test_concurrent_last_writer_wins_on_same_leaf() -> None:
    # Registering the same (backend, leaf) from many threads MUST converge
    # to exactly one winner — no torn state, no raised exceptions.
    reg = TranslatorRegistry()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            reg.register("sql", "shared", lambda s, i=i: i)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    spec = PredicateSpecification[int]("shared", lambda x: True)
    final = reg.translate("sql", spec)
    # Final value MUST be one of the writers' ids (linearizable).
    assert isinstance(final, int)
    assert 0 <= final < 50
