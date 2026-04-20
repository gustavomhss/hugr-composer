"""Concurrency / linearizability harness for CircuitBreaker.

Confirms that concurrent recordings, probe requests, and force_open races
never corrupt the state machine and respect the half_open permit bound.
"""

from __future__ import annotations

import threading
import time

from CircuitBreaker import InMemoryCircuitBreaker


def test_concurrent_mixed_outcomes_preserve_state_enum() -> None:
    breaker = InMemoryCircuitBreaker("svc", minimum_number_of_calls=3)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def fail_worker() -> None:
        try:
            for _ in range(200):
                breaker.on_failure(RuntimeError("x"), 1.0)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def succ_worker() -> None:
        try:
            for _ in range(200):
                breaker.on_success(1.0)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=fail_worker) for _ in range(4)]
    ts += [threading.Thread(target=succ_worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert breaker.state in ("closed", "open", "half_open")


def test_concurrent_probe_permits_respect_bound() -> None:
    breaker = InMemoryCircuitBreaker(
        "svc", permitted_calls_in_half_open=3, cooldown_ms=1,
    )
    breaker.force_open("test")
    time.sleep(0.01)

    granted: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = breaker.allow_probe()
        with lock:
            granted.append(ok)

    ts = [threading.Thread(target=worker) for _ in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # At most 3 probe permits granted across 50 workers.
    assert sum(1 for g in granted if g) == 3


def test_concurrent_force_open_is_single_transition() -> None:
    breaker = InMemoryCircuitBreaker("svc")
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            breaker.force_open(f"race-{i}")
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert breaker.state == "open"
    # Exactly one open transition event across 40 concurrent force_open calls.
    open_events = [e for e in breaker.events if e.to_state == "open"]
    assert len(open_events) == 1


def test_concurrent_reads_do_not_observe_illegal_state() -> None:
    breaker = InMemoryCircuitBreaker(
        "svc", minimum_number_of_calls=2, cooldown_ms=5,
    )
    seen: list[str] = []
    stop = threading.Event()
    lock = threading.Lock()

    def reader() -> None:
        while not stop.is_set():
            s = breaker.state
            with lock:
                seen.append(s)

    def driver() -> None:
        breaker.on_failure(RuntimeError("x"), 1.0)
        breaker.on_failure(RuntimeError("x"), 1.0)
        time.sleep(0.02)
        breaker.allow_probe()
        stop.set()

    r = threading.Thread(target=reader)
    d = threading.Thread(target=driver)
    r.start()
    d.start()
    d.join()
    r.join(timeout=1.0)
    stop.set()
    assert all(s in ("closed", "open", "half_open") for s in seen)
