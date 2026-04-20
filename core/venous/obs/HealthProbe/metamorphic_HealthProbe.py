"""Metamorphic + differential tests for HealthProbe.

Algebraic laws:
- worst-wins aggregation is idempotent: aggregating the same set twice yields same status.
- worst-wins is commutative in registration order.
- Adding a UP dependency does not worsen the aggregated status (monotonicity).
- sanitize_report is idempotent under a second application.
"""

from __future__ import annotations

import pytest

from HealthProbe import (
    BaseHealthProbe,
    HealthReport,
    HealthStatus,
    sanitize_report,
)


class _Fixed:
    def __init__(self, name: str, status: HealthStatus) -> None:
        self.name = name
        self._s = status

    async def liveness(self) -> HealthReport:
        return HealthReport(self._s)

    async def readiness(self) -> HealthReport:
        return HealthReport(self._s)

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_metamorphic_readiness_idempotent_on_stable_deps() -> None:
    probe = BaseHealthProbe("p", debounce_s=0)
    probe.register_dependency("a", _Fixed("a", HealthStatus.UP))
    probe.register_dependency("b", _Fixed("b", HealthStatus.DEGRADED))
    first = await probe.readiness()
    second = await probe.readiness()
    assert first.status is second.status


@pytest.mark.asyncio
async def test_metamorphic_aggregation_order_independent() -> None:
    # Register the same deps in two different orders; result status is the same.
    p1 = BaseHealthProbe("p1", debounce_s=0)
    p2 = BaseHealthProbe("p2", debounce_s=0)
    p1.register_dependency("a", _Fixed("a", HealthStatus.UP))
    p1.register_dependency("b", _Fixed("b", HealthStatus.DOWN))
    p2.register_dependency("b", _Fixed("b", HealthStatus.DOWN))
    p2.register_dependency("a", _Fixed("a", HealthStatus.UP))
    r1 = await p1.readiness()
    r2 = await p2.readiness()
    assert r1.status is r2.status is HealthStatus.DOWN


@pytest.mark.asyncio
async def test_metamorphic_adding_up_dep_does_not_worsen() -> None:
    probe = BaseHealthProbe("p", debounce_s=0)
    probe.register_dependency("db", _Fixed("db", HealthStatus.DEGRADED))
    before = await probe.readiness()
    probe.register_dependency("cache", _Fixed("cache", HealthStatus.UP))
    after = await probe.readiness()
    assert after.status is before.status


@pytest.mark.asyncio
async def test_metamorphic_adding_down_dep_cannot_improve() -> None:
    probe = BaseHealthProbe("p", debounce_s=0)
    probe.register_dependency("ok", _Fixed("ok", HealthStatus.UP))
    before = await probe.readiness()
    assert before.status is HealthStatus.UP
    probe.register_dependency("bad", _Fixed("bad", HealthStatus.DOWN))
    after = await probe.readiness()
    assert after.status is HealthStatus.DOWN


def test_metamorphic_sanitize_idempotent() -> None:
    raw = HealthReport(HealthStatus.UP, {"api_key": "sk-123", "region": "eu"})
    once = sanitize_report(raw)
    twice = sanitize_report(once)
    assert dict(once.details) == dict(twice.details)


@pytest.mark.asyncio
async def test_differential_status_ordering_total() -> None:
    # UP < DEGRADED < DOWN — worst-of every pair equals the rank-max element.
    order = [HealthStatus.UP, HealthStatus.DEGRADED, HealthStatus.DOWN]
    for i, a in enumerate(order):
        for j, b in enumerate(order):
            worst_expected = order[max(i, j)]
            probe = BaseHealthProbe(f"p_{i}_{j}", debounce_s=0)
            probe.register_dependency("x", _Fixed("x", a))
            probe.register_dependency("y", _Fixed("y", b))
            actual = await probe.readiness()
            assert actual.status is worst_expected
