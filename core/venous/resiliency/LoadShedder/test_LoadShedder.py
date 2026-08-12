"""Unit tests for LoadShedder — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from LoadShedder import (
    AdmissionToken,
    InMemoryLoadShedder,
    LoadShedderInvariantError,
    SealedAdmit,
)


# ---------------------------------------------------------------------------
# Test clock helper
# ---------------------------------------------------------------------------
class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# LSH_INV_01 — priority ordering: never admit low while rejecting high
# ---------------------------------------------------------------------------
def test_inv_priority_order_confirms() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock)
    # Healthy pressure — everything is admitted.
    assert s.admit("critical", queue_depth=0, cpu_load_ewma=0.1) is True
    assert s.admit("normal", queue_depth=0, cpu_load_ewma=0.1) is True
    assert s.admit("sheddable_plus", queue_depth=0, cpu_load_ewma=0.1) is True
    assert s.admit("sheddable", queue_depth=0, cpu_load_ewma=0.1) is True
    assert s.current_cutoff() == "sheddable"


def test_inv_priority_order_prevents() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    # Extreme overload — only critical admitted; lower classes rejected.
    clock.advance(1.0)
    assert s.admit("sheddable", queue_depth=100, cpu_load_ewma=0.99) is False
    # Critical still passes under the same pressure.
    assert s.admit("critical", queue_depth=100, cpu_load_ewma=0.99) is True
    assert s.current_cutoff() == "critical"
    # Lower classes remain rejected — priority order NEVER inverts.
    assert s.admit("normal", queue_depth=100, cpu_load_ewma=0.99) is False
    assert s.admit("sheddable_plus", queue_depth=100, cpu_load_ewma=0.99) is False


def test_inv_priority_order_under_failure() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    # Apply sustained heavy pressure; then bombard with mixed priorities.
    clock.advance(1.0)
    outcomes: dict[str, list[bool]] = {"critical": [], "normal": [], "sheddable_plus": [], "sheddable": []}
    for _ in range(100):
        for p in ("critical", "normal", "sheddable_plus", "sheddable"):
            outcomes[p].append(s.admit(p, queue_depth=200, cpu_load_ewma=0.99))
    # LSH-INV-01: critical MUST have highest admission rate, sheddable lowest.
    rates = {p: sum(v) / len(v) for p, v in outcomes.items()}
    assert rates["critical"] >= rates["normal"]
    assert rates["normal"] >= rates["sheddable_plus"]
    assert rates["sheddable_plus"] >= rates["sheddable"]
    # Under extreme pressure the lowest class is shed entirely.
    assert rates["sheddable"] == 0.0


# ---------------------------------------------------------------------------
# LSH_INV_02 — rejection emits explicit overload signal + retry-after
# ---------------------------------------------------------------------------
def test_inv_overload_signal_confirms() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    clock.advance(1.0)
    assert s.admit("sheddable", queue_depth=100, cpu_load_ewma=0.99) is False
    sig = s.rejection_signal()
    assert sig.http_status == 503
    assert sig.grpc_status == "UNAVAILABLE"
    assert sig.retry_after_seconds > 0.0
    assert sig.reason == "load_shed"


def test_inv_overload_signal_prevents() -> None:
    # Under healthy load, the signal must still be well-formed (no partial fields).
    s = InMemoryLoadShedder()
    sig = s.rejection_signal()
    assert sig.http_status == 503
    assert sig.retry_after_seconds > 0.0
    # Retry-after MUST NEVER be zero or negative — clients would hot-loop.
    assert sig.retry_after_seconds >= 0.1


def test_inv_overload_signal_under_failure() -> None:
    # When the control interval is misconfigured (but positive), retry-after
    # still respects the floor.
    s = InMemoryLoadShedder(control_interval_ms=1)
    sig = s.rejection_signal()
    assert sig.retry_after_seconds >= 0.1


# ---------------------------------------------------------------------------
# LSH_INV_03 — cutoff changes at most once per control_interval_ms
# ---------------------------------------------------------------------------
def test_inv_hysteresis_confirms() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=100)
    clock.advance(1.0)
    s.admit("sheddable", queue_depth=100, cpu_load_ewma=0.99)
    first = s.current_cutoff()
    assert first == "critical"
    # Immediately (before control_interval) pressure drops — cutoff MUST hold.
    s.admit("critical", queue_depth=0, cpu_load_ewma=0.05)
    assert s.current_cutoff() == first


def test_inv_hysteresis_prevents() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=100)
    clock.advance(1.0)
    s.admit("sheddable", queue_depth=100, cpu_load_ewma=0.99)
    assert s.current_cutoff() == "critical"
    # Oscillating pressure WITHIN the interval — cutoff MUST NOT flap.
    for _ in range(50):
        s.admit("normal", queue_depth=0, cpu_load_ewma=0.05)
        s.admit("normal", queue_depth=100, cpu_load_ewma=0.99)
    assert s.current_cutoff() == "critical"


def test_inv_hysteresis_under_failure() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=100)
    clock.advance(1.0)
    s.admit("sheddable", queue_depth=100, cpu_load_ewma=0.99)
    assert s.current_cutoff() == "critical"
    # After waiting the control interval, the cutoff MAY change.
    clock.advance(0.2)
    s.admit("critical", queue_depth=0, cpu_load_ewma=0.05)
    assert s.current_cutoff() != "critical"


# ---------------------------------------------------------------------------
# LSH_INV_04 — admitted requests are never shed later
# ---------------------------------------------------------------------------
def test_inv_no_shed_after_admit_confirms() -> None:
    s = InMemoryLoadShedder()
    sealed = SealedAdmit(s)
    token = sealed.admit("critical", queue_depth=0, cpu_load_ewma=0.1)
    assert isinstance(token, AdmissionToken)
    # Downstream stage calling pass_through MUST NOT raise.
    sealed.pass_through(token)


def test_inv_no_shed_after_admit_prevents() -> None:
    s = InMemoryLoadShedder()
    sealed = SealedAdmit(s)
    # Fabricated token (not issued by the gate) MUST be rejected.
    fake = AdmissionToken(token_id=9999, priority="critical", cutoff_at_admit="sheddable")
    with pytest.raises(LoadShedderInvariantError):
        sealed.pass_through(fake)


def test_inv_no_shed_after_admit_under_failure() -> None:
    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    sealed = SealedAdmit(s)
    # Drive into overload AFTER issuing a token. The previously admitted token
    # MUST still pass through — LSH-INV-04.
    token = sealed.admit("critical", queue_depth=0, cpu_load_ewma=0.05)
    assert token is not None
    clock.advance(1.0)
    s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)  # force cutoff change
    sealed.pass_through(token)  # NEVER raises for an issued token


# ---------------------------------------------------------------------------
# LSH_INV_05 — cutoff is published as a metric
# ---------------------------------------------------------------------------
def test_inv_publish_cutoff_confirms() -> None:
    emitted: list[tuple[str, float, dict[str, str]]] = []

    def sink(name: str, value: float, labels: dict[str, str]) -> None:
        emitted.append((name, value, labels))

    s = InMemoryLoadShedder(metric_sink=sink)
    # Construction MUST publish the initial cutoff.
    assert emitted
    assert emitted[0][0] == "load_shedder.current_cutoff"
    assert "cutoff" in emitted[0][2]
    # current_cutoff() is always observable.
    assert s.current_cutoff() in ("critical", "normal", "sheddable_plus", "sheddable")


def test_inv_publish_cutoff_prevents() -> None:
    # A broken metric sink MUST NOT break admission (LSH-INV-04/-05 interaction).
    def broken(_n: str, _v: float, _l: dict[str, str]) -> None:
        raise RuntimeError("metric backend down")

    s = InMemoryLoadShedder(metric_sink=broken)
    assert s.admit("critical", queue_depth=0, cpu_load_ewma=0.1) is True


def test_inv_publish_cutoff_under_failure() -> None:
    emitted: list[tuple[str, float, dict[str, str]]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def sink(name: str, value: float, labels: dict[str, str]) -> None:
        with lock:
            emitted.append((name, value, labels))

    clock = _FakeClock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, metric_sink=sink)

    def worker() -> None:
        try:
            clock.advance(0.02)
            s.admit("critical", queue_depth=200, cpu_load_ewma=0.99)
            s.admit("sheddable", queue_depth=0, cpu_load_ewma=0.05)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Every cutoff transition fired a metric publication.
    assert all(e[0] == "load_shedder.current_cutoff" for e in emitted)
