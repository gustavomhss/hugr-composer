"""Concurrency / linearizability harness for Repository.

Confirms that concurrent add / remove / get calls never corrupt the internal
store or the singleton registry.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from Repository import ConcreteRepository, RepositoryInvariantError


@dataclass
class Node:
    id: int


class _StubUoW:
    def __init__(self) -> None:
        self.new = 0
        self.dirty = 0
        self.removed = 0
        self._lock = threading.Lock()

    def register_new(self, obj: object) -> None:
        with self._lock:
            self.new += 1

    def register_dirty(self, obj: object) -> None:
        with self._lock:
            self.dirty += 1

    def register_removed(self, obj: object) -> None:
        with self._lock:
            self.removed += 1


def test_concurrent_adds_preserve_tracked_count() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Node] = ConcreteRepository(Node, uow, shard="conc-1")
    try:
        nodes = [Node(id=i) for i in range(300)]

        def worker(chunk: list[Node]) -> None:
            for n in chunk:
                repo.add(n)

        batches = [nodes[i::5] for i in range(5)]
        ts = [threading.Thread(target=worker, args=(b,)) for b in batches]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert uow.new == 300
        assert len(repo.tracked_ids) == 300
    finally:
        repo.close()


def test_concurrent_duplicate_repo_registration_only_one_wins() -> None:
    uow = _StubUoW()
    winners: list[ConcreteRepository[Node]] = []
    rejected = 0
    lock = threading.Lock()

    def build() -> None:
        nonlocal rejected
        try:
            r: ConcreteRepository[Node] = ConcreteRepository(
                Node, uow, shard="conc-singleton",
            )
            with lock:
                winners.append(r)
        except RepositoryInvariantError:
            with lock:
                rejected += 1

    ts = [threading.Thread(target=build) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    try:
        assert len(winners) == 1
        assert rejected == 31
    finally:
        for w in winners:
            w.close()


def test_concurrent_get_reads_never_mismatch() -> None:
    uow = _StubUoW()
    repo: ConcreteRepository[Node] = ConcreteRepository(Node, uow, shard="conc-reads")
    try:
        for i in range(100):
            repo.add(Node(id=i))

        mismatches: list[int] = []
        lock = threading.Lock()

        def reader() -> None:
            for i in range(100):
                got = repo.get(i)
                if got is None or got.id != i:
                    with lock:
                        mismatches.append(i)

        ts = [threading.Thread(target=reader) for _ in range(16)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert mismatches == []
    finally:
        repo.close()
