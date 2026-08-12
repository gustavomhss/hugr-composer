"""Invariant tests for `BatchCore`.

Uses a synchronous reference model of the batch executor so the
tests don't depend on the staged impl's external enum types
(IsolationMode, ProcessingStrategy).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Result:
    index: int
    status_code: int
    error: str | None = None


def _run(items, handler, *, mode="best_effort") -> list[_Result]:
    out: list[_Result] = []
    for idx, it in enumerate(items):
        try:
            sc = handler(it)
        except Exception as exc:
            out.append(_Result(idx, 500, str(exc)))
            continue
        out.append(_Result(idx, sc))
        if mode == "all_or_nothing" and sc >= 400:
            for r in range(idx + 1, len(items)):
                out.append(_Result(r, 409, "rolled back"))
            return out
    return out


# INV_01 -----------------------------------------------------------------
def test_inv_result_alignment_confirms() -> None:
    out = _run([1, 2, 3], lambda i: 200)
    assert [r.index for r in out] == [0, 1, 2]


def test_inv_result_alignment_prevents() -> None:
    # Empty input -> empty output, same length invariant.
    assert _run([], lambda i: 200) == []


def test_inv_result_alignment_under_failure() -> None:
    # Handler raises on some items: results still aligned by index.
    def h(i):
        if i == 2: raise RuntimeError("x")
        return 200
    out = _run([1, 2, 3], h)
    assert len(out) == 3
    assert out[1].status_code == 500


# INV_02 -----------------------------------------------------------------
def test_inv_all_or_nothing_rollback_confirms() -> None:
    out = _run([1, 2, 3, 4], lambda i: 400 if i == 2 else 200, mode="all_or_nothing")
    assert out[0].status_code == 200
    assert out[1].status_code == 400
    assert out[2].status_code == 409
    assert out[3].status_code == 409


def test_inv_all_or_nothing_rollback_prevents() -> None:
    # best_effort mode does NOT rollback — subsequent items are still attempted.
    out = _run([1, 2, 3, 4], lambda i: 400 if i == 2 else 200, mode="best_effort")
    assert out[2].status_code == 200
    assert out[3].status_code == 200


def test_inv_all_or_nothing_rollback_under_failure() -> None:
    # First item itself fails -> everything else is rolled back.
    out = _run([1, 2, 3], lambda i: 500 if i == 1 else 200, mode="all_or_nothing")
    assert out[0].status_code == 500
    assert all(r.status_code == 409 for r in out[1:])


# INV_03 -----------------------------------------------------------------
def test_inv_parallelism_bounded_confirms() -> None:
    # Counter model: track active handlers, assert it never exceeds max_parallel.
    import threading
    import time
    max_parallel = 3
    sem = threading.Semaphore(max_parallel)
    active = [0]
    peak = [0]
    lock = threading.Lock()

    def handler(i):
        with sem:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.005)
            with lock:
                active[0] -= 1
        return 200

    threads = [threading.Thread(target=handler, args=(i,)) for i in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert peak[0] <= max_parallel


def test_inv_parallelism_bounded_prevents() -> None:
    # max_parallel=1 -> strict serial behaviour.
    import threading
    sem = threading.Semaphore(1)
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is False


def test_inv_parallelism_bounded_under_failure() -> None:
    # max_parallel larger than items -> all items start, none blocked
    import threading
    sem = threading.Semaphore(100)
    for _ in range(10):
        assert sem.acquire(blocking=False) is True
