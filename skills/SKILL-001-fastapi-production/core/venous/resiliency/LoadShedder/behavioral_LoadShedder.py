"""Behavioral end-to-end scenarios for LoadShedder — proves invariants at runtime."""

from __future__ import annotations

from LoadShedder import (
    InMemoryLoadShedder,
    SealedAdmit,
    compose_ewma,
    compose_max,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def test_scenario_overload_protects_critical_traffic() -> None:
    """Under sustained overload, critical requests always succeed and batch is shed."""
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=50)
    clock.advance(1.0)
    crit_ok = 0
    batch_ok = 0
    for _ in range(200):
        if s.admit("critical", queue_depth=150, cpu_load_ewma=0.97):
            crit_ok += 1
        if s.admit("sheddable", queue_depth=150, cpu_load_ewma=0.97):
            batch_ok += 1
    assert crit_ok == 200
    assert batch_ok == 0


def test_scenario_healthy_regime_admits_everything() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock)
    clock.advance(1.0)
    for p in ("critical", "normal", "sheddable_plus", "sheddable"):
        for _ in range(25):
            assert s.admit(p, queue_depth=0, cpu_load_ewma=0.1) is True
    assert s.current_cutoff() == "sheddable"
    assert s.shed_rate() == 0.0


def test_scenario_oscillating_pressure_does_not_flap_cutoff() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=200)
    clock.advance(1.0)
    # First admit under heavy pressure — cutoff moves to critical.
    s.admit("sheddable", queue_depth=150, cpu_load_ewma=0.99)
    baseline = s.current_cutoff()
    # Oscillate quickly — cutoff MUST hold (LSH-INV-03).
    for _ in range(50):
        s.admit("normal", queue_depth=0, cpu_load_ewma=0.05)
        s.admit("normal", queue_depth=200, cpu_load_ewma=0.99)
    assert s.current_cutoff() == baseline


def test_scenario_sealed_token_survives_cutoff_change() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    sealed = SealedAdmit(s)
    token = sealed.admit("critical", queue_depth=0, cpu_load_ewma=0.1)
    assert token is not None
    clock.advance(1.0)
    # Cutoff moves to critical under overload — issued token MUST still pass.
    s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    sealed.pass_through(token)  # LSH-INV-04


def test_scenario_shed_rate_tracks_rejections() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    clock.advance(1.0)
    for _ in range(100):
        s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    assert s.shed_rate() >= 0.9


def test_scenario_composition_adapter_swappable() -> None:
    clock = _Clock()
    # `compose_ewma` is smoother than `compose_max`; both MUST converge under
    # saturated signals to the same aggressive cutoff.
    s_max = InMemoryLoadShedder(clock=clock, control_interval_ms=10, composition=compose_max)
    s_ewma = InMemoryLoadShedder(clock=clock, control_interval_ms=10, composition=compose_ewma)
    clock.advance(1.0)
    s_max.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    s_ewma.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    assert s_max.current_cutoff() == "critical"
    assert s_ewma.current_cutoff() == "critical"


def test_scenario_rejection_signal_carries_cutoff() -> None:
    clock = _Clock()
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    clock.advance(1.0)
    admitted = s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    assert admitted is False
    sig = s.rejection_signal()
    assert sig.current_cutoff == "critical"
    assert sig.http_status == 503
