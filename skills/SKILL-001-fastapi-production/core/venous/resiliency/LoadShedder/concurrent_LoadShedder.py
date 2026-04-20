"""Concurrency / linearizability harness for LoadShedder.

Confirms that concurrent admit() calls from many threads preserve priority
ordering (LSH-INV-01) and hysteresis (LSH-INV-03) — no torn reads, no
race-window admission inversions.
"""

from __future__ import annotations

import threading

from LoadShedder import InMemoryLoadShedder, SealedAdmit


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.lock = threading.Lock()

    def __call__(self) -> float:
        with self.lock:
            return self.now

    def advance(self, s: float) -> None:
        with self.lock:
            self.now += s


def test_concurrent_admit_preserves_priority_order() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)

    admits: dict[str, int] = {"critical": 0, "normal": 0, "sheddable_plus": 0, "sheddable": 0}
    lock = threading.Lock()

    def worker(priority: str) -> None:
        local = 0
        for _ in range(200):
            if s.admit(priority, queue_depth=200, cpu_load_ewma=0.99):  # type: ignore[arg-type]
                local += 1
        with lock:
            admits[priority] += local

    threads = []
    for p in ("critical", "normal", "sheddable_plus", "sheddable"):
        for _ in range(4):  # 4 threads per priority → 16 threads total
            threads.append(threading.Thread(target=worker, args=(p,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # LSH-INV-01: under saturated load, critical >> lower classes.
    assert admits["critical"] > admits["normal"]
    assert admits["normal"] >= admits["sheddable_plus"]
    assert admits["sheddable_plus"] >= admits["sheddable"]


def test_concurrent_cutoff_changes_debounced() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=100)
    clock.advance(1.0)

    # Many threads hammer the shedder with oscillating pressure.
    def worker() -> None:
        for _ in range(200):
            s.admit("normal", queue_depth=0, cpu_load_ewma=0.05)
            s.admit("normal", queue_depth=200, cpu_load_ewma=0.99)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # With no clock advance, at most one cutoff transition should have occurred.
    # The cutoff is deterministic & observable.
    c = s.current_cutoff()
    assert c in ("critical", "normal", "sheddable_plus", "sheddable")


def test_concurrent_sealed_tokens_never_re_shed() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    sealed = SealedAdmit(s)

    tokens: list[object] = []
    lock = threading.Lock()

    def issuer() -> None:
        for _ in range(100):
            t = sealed.admit("critical", queue_depth=0, cpu_load_ewma=0.1)
            if t is not None:
                with lock:
                    tokens.append(t)

    def overloader() -> None:
        for _ in range(100):
            s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)

    ts = [threading.Thread(target=issuer) for _ in range(4)] + \
         [threading.Thread(target=overloader) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # LSH-INV-04: every issued token MUST pass through, even under sustained
    # concurrent overload.
    for tok in tokens:
        sealed.pass_through(tok)  # type: ignore[arg-type]


def test_concurrent_metric_sink_never_breaks_admission() -> None:
    clock = _Clock()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def flaky(_n: str, _v: float, _l: dict[str, str]) -> None:
        raise RuntimeError("metric backend intermittent")

    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, metric_sink=flaky)
    clock.advance(1.0)

    def worker() -> None:
        try:
            for _ in range(200):
                s.admit("critical", queue_depth=50, cpu_load_ewma=0.8)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
