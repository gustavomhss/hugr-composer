"""Chaos / fault-injection for HealthProbe.

Game-day scenarios: probe hangs, throws, returns wild details, blips, many
concurrent callers. HealthProbe MUST remain correct under each.
"""

from __future__ import annotations

import asyncio

import pytest

from HealthProbe import (
    BaseHealthProbe,
    HealthProbeInvariantError,
    HealthReport,
    HealthStatus,
)


class _Throws:
    name = "bad"

    async def liveness(self) -> HealthReport:
        raise RuntimeError("boom")

    async def readiness(self) -> HealthReport:
        raise RuntimeError("boom")

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


class _Hangs:
    name = "hang"

    async def liveness(self) -> HealthReport:
        await asyncio.sleep(60)
        return HealthReport(HealthStatus.UP)

    async def readiness(self) -> HealthReport:
        await asyncio.sleep(60)
        return HealthReport(HealthStatus.UP)

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


class _LeaksSecrets:
    name = "leaky"

    async def liveness(self) -> HealthReport:
        return HealthReport(
            HealthStatus.UP,
            {"dsn": "postgres://user:hunter2@db/app", "token": "sk-secret"},
        )

    async def readiness(self) -> HealthReport:
        return HealthReport(
            HealthStatus.UP,
            {"dsn": "postgres://user:hunter2@db/app", "token": "sk-secret"},
        )

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_chaos_throwing_dependency_degrades_gracefully() -> None:
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency("bad", _Throws())
    report = await probe.readiness()
    assert report.status is HealthStatus.DOWN


@pytest.mark.asyncio
async def test_chaos_hanging_dependency_times_out() -> None:
    probe = BaseHealthProbe("svc", timeout_s=0.1, debounce_s=0)
    probe.register_dependency("hang", _Hangs())
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    report = await probe.readiness()
    elapsed = loop.time() - t0
    assert report.status is HealthStatus.DOWN
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_chaos_mixed_failure_modes_combine() -> None:
    probe = BaseHealthProbe("svc", timeout_s=0.1, debounce_s=0)
    probe.register_dependency("throws", _Throws())
    probe.register_dependency("hangs", _Hangs())
    probe.register_dependency("leaks", _LeaksSecrets())
    report = await probe.readiness()
    # Down by worst-wins. No exception propagates.
    assert report.status is HealthStatus.DOWN
    # Secret scrubbing still engaged even though the aggregated status is DOWN.
    for v in report.details.values():
        assert "hunter2" not in v
        assert "sk-secret" not in v


@pytest.mark.asyncio
async def test_chaos_concurrent_readiness_is_safe() -> None:
    probe = BaseHealthProbe("svc", debounce_s=0)
    for i in range(5):
        probe.register_dependency(f"d{i}", _LeaksSecrets())
    results = await asyncio.gather(*(probe.readiness() for _ in range(50)))
    assert all(r.status in (HealthStatus.UP, HealthStatus.DEGRADED) for r in results)


@pytest.mark.asyncio
async def test_chaos_duplicate_registration_rejected() -> None:
    probe = BaseHealthProbe("svc")
    probe.register_dependency("db", _LeaksSecrets())
    with pytest.raises(HealthProbeInvariantError):
        probe.register_dependency("db", _LeaksSecrets())


@pytest.mark.asyncio
async def test_chaos_self_registration_rejected() -> None:
    probe = BaseHealthProbe("svc")
    with pytest.raises(HealthProbeInvariantError):
        probe.register_dependency("self", probe)


@pytest.mark.asyncio
async def test_chaos_liveness_never_affected_by_dep_chaos() -> None:
    # Liveness must report UP even under every dependency failure mode.
    probe = BaseHealthProbe("svc", timeout_s=0.1, debounce_s=0)
    probe.register_dependency("throws", _Throws())
    probe.register_dependency("hangs", _Hangs())
    report = await probe.liveness()
    assert report.status is HealthStatus.UP
