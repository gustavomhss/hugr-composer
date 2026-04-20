"""Chaos / game-day tests for LoadShedder.

Simulates adversarial conditions:
- unknown priorities
- negative / saturated signals
- flaky metric sinks
- sustained sustained overload then sudden recovery
- signal spikes shorter than the control interval
- invalid construction parameters
"""

from __future__ import annotations

import threading

import pytest

from LoadShedder import (
    InMemoryLoadShedder,
    LoadShedderInvariantError,
    SealedAdmit,
    compose_max,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def test_chaos_unknown_priority_rejected() -> None:
    s = InMemoryLoadShedder()
    with pytest.raises(LoadShedderInvariantError):
        s.admit("elevated", queue_depth=0, cpu_load_ewma=0.1)  # type: ignore[arg-type]


def test_chaos_negative_queue_depth_rejected() -> None:
    s = InMemoryLoadShedder()
    with pytest.raises(ValueError):
        s.admit("critical", queue_depth=-1, cpu_load_ewma=0.1)


def test_chaos_over_saturated_cpu_clamped() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    # cpu_load_ewma well above 1.0 MUST NOT break the shedder — it is clamped.
    s.admit("sheddable", queue_depth=200, cpu_load_ewma=9999.0)
    assert s.current_cutoff() == "critical"


def test_chaos_flaky_metric_sink_preserves_admit_path() -> None:
    calls = {"n": 0}

    def flaky(_n: str, _v: float, _l: dict[str, str]) -> None:
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise RuntimeError("intermittent")

    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, metric_sink=flaky)
    clock.advance(1.0)
    for _ in range(50):
        assert s.admit("critical", queue_depth=100, cpu_load_ewma=0.9) in (True, False)


def test_chaos_sustained_overload_then_recovery() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=50)
    clock.advance(1.0)
    # Push into overload.
    for _ in range(100):
        s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    assert s.current_cutoff() == "critical"
    # Let the control interval elapse and emit healthy signals.
    clock.advance(0.2)
    for _ in range(100):
        s.admit("critical", queue_depth=0, cpu_load_ewma=0.05)
    # Cutoff should have relaxed away from critical.
    assert s.current_cutoff() != "critical"


def test_chaos_signal_spike_shorter_than_interval_ignored() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=500)
    clock.advance(1.0)
    # Brief spike — one admit with heavy signals moves cutoff to critical.
    s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    assert s.current_cutoff() == "critical"
    # Immediate recovery signals do NOT flap cutoff — hysteresis holds.
    for _ in range(10):
        s.admit("critical", queue_depth=0, cpu_load_ewma=0.01)
    assert s.current_cutoff() == "critical"


def test_chaos_invalid_construction_rejected() -> None:
    with pytest.raises(ValueError):
        InMemoryLoadShedder(control_interval_ms=0)
    with pytest.raises(ValueError):
        InMemoryLoadShedder(queue_saturation=0)
    with pytest.raises(ValueError):
        InMemoryLoadShedder(window_size=0)


def test_chaos_concurrent_admit_burst() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, composition=compose_max)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(500):
                s.admit("normal", queue_depth=100, cpu_load_ewma=0.92)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Counters must be consistent — no torn state.
    assert s.admitted_total + s.rejected_total == 4000


def test_chaos_sealed_token_stress() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    sealed = SealedAdmit(s)
    tokens = []
    for _ in range(200):
        tok = sealed.admit("critical", queue_depth=150, cpu_load_ewma=0.97)
        if tok is not None:
            tokens.append(tok)
    for tok in tokens:
        sealed.pass_through(tok)  # LSH-INV-04 — every issued token passes.


def test_chaos_rejection_signal_always_actionable() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    for _ in range(10):
        sig = s.rejection_signal()
        assert sig.http_status == 503
        assert sig.grpc_status == "UNAVAILABLE"
        assert sig.retry_after_seconds >= 0.1
