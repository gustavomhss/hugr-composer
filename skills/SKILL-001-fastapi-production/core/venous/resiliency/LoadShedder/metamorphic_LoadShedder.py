"""Metamorphic + differential properties for LoadShedder.

Algebraic laws:
- Monotonicity in pressure: increasing load NEVER increases admission rate for a given priority.
- Monotonicity in priority: for fixed signals, a HIGHER-priority request is admitted at least as often as a lower-priority one.
- Differential parity: max vs ewma composition agree at pressure extremes (0 and 1).
- Idempotence of observation: admit() is pure-functional w.r.t. repeated identical calls within one control interval.
"""

from __future__ import annotations

from LoadShedder import (
    InMemoryLoadShedder,
    compose_ewma,
    compose_max,
    compose_quantile,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def test_metamorphic_higher_priority_admits_at_least_as_often() -> None:
    clock_a = _Clock()
    clock_b = _Clock()
    clock_a.advance(1.0)
    clock_b.advance(1.0)
    s_crit = InMemoryLoadShedder(clock=clock_a, control_interval_ms=10)
    s_shed = InMemoryLoadShedder(clock=clock_b, control_interval_ms=10)
    crit_ok = 0
    shed_ok = 0
    for _ in range(200):
        if s_crit.admit("critical", queue_depth=100, cpu_load_ewma=0.88):
            crit_ok += 1
        if s_shed.admit("sheddable", queue_depth=100, cpu_load_ewma=0.88):
            shed_ok += 1
    assert crit_ok >= shed_ok


def test_metamorphic_monotonic_in_pressure() -> None:
    # At higher pressure, admission rate for a sheddable class is <= that at lower pressure.
    clock_lo = _Clock()
    clock_hi = _Clock()
    clock_lo.advance(1.0)
    clock_hi.advance(1.0)
    s_lo = InMemoryLoadShedder(clock=clock_lo, control_interval_ms=10)
    s_hi = InMemoryLoadShedder(clock=clock_hi, control_interval_ms=10)
    lo_ok = 0
    hi_ok = 0
    for _ in range(200):
        if s_lo.admit("sheddable", queue_depth=10, cpu_load_ewma=0.20):
            lo_ok += 1
        if s_hi.admit("sheddable", queue_depth=100, cpu_load_ewma=0.99):
            hi_ok += 1
    assert lo_ok >= hi_ok


def test_metamorphic_composition_parity_at_extremes() -> None:
    # At cpu=1, queue saturated, all three adapters agree → cutoff "critical".
    clock = _Clock()
    clock.advance(1.0)
    for adapter in (compose_max, compose_ewma, compose_quantile):
        s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, composition=adapter)
        s.admit("sheddable", queue_depth=200, cpu_load_ewma=1.0)
        assert s.current_cutoff() == "critical"


def test_differential_max_vs_ewma_at_zero_pressure() -> None:
    # At cpu=0, queue=0: both adapters produce pressure=0 → cutoff stays "sheddable".
    clock = _Clock()
    clock.advance(1.0)
    s_max = InMemoryLoadShedder(clock=clock, control_interval_ms=10, composition=compose_max)
    s_ewma = InMemoryLoadShedder(clock=clock, control_interval_ms=10, composition=compose_ewma)
    for _ in range(50):
        assert s_max.admit("sheddable", queue_depth=0, cpu_load_ewma=0.0) is True
        assert s_ewma.admit("sheddable", queue_depth=0, cpu_load_ewma=0.0) is True
    assert s_max.current_cutoff() == s_ewma.current_cutoff() == "sheddable"


def test_metamorphic_cutoff_repeatable_within_interval() -> None:
    # Within one control interval, identical calls produce identical decisions for critical.
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=500)
    outcomes = [s.admit("critical", queue_depth=50, cpu_load_ewma=0.5) for _ in range(100)]
    # Critical is admitted always (cutoff is at worst "critical", rank 0 <= 0).
    assert all(outcomes)


def test_metamorphic_shed_rate_bounded_zero_one() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10)
    for _ in range(50):
        s.admit("sheddable", queue_depth=200, cpu_load_ewma=0.99)
    r = s.shed_rate()
    assert 0.0 <= r <= 1.0


def test_differential_admit_rate_sums_match_counts() -> None:
    clock = _Clock()
    clock.advance(1.0)
    s = InMemoryLoadShedder(clock=clock, control_interval_ms=10, window_size=4096)
    admits = 0
    rejects = 0
    for i in range(200):
        p = "critical" if i % 2 == 0 else "sheddable"
        ok = s.admit(p, queue_depth=200, cpu_load_ewma=0.99)  # type: ignore[arg-type]
        if ok:
            admits += 1
        else:
            rejects += 1
    # Differential: internal counters match external observation.
    assert s.admitted_total == admits
    assert s.rejected_total == rejects
    # shed_rate is consistent with observed ratio.
    total = admits + rejects
    if total > 0:
        observed = rejects / total
        assert abs(s.shed_rate() - observed) < 1e-9
