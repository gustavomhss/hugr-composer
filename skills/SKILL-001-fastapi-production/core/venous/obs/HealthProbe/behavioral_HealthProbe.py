"""Behavioral end-to-end scenarios for HealthProbe — proves invariants at runtime."""

from __future__ import annotations

import asyncio

import pytest

from HealthProbe import (
    BaseHealthProbe,
    DependencyRequirement,
    HealthProbeRegistry,
    HealthReport,
    HealthStatus,
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
async def test_scenario_db_down_yields_readiness_down() -> None:
    app = BaseHealthProbe("api", debounce_s=0)
    app.register_dependency("primary_db", _Fixed("db", HealthStatus.DOWN))
    report = await app.readiness()
    assert report.status is HealthStatus.DOWN
    # Liveness stays UP — would be wrong to restart for a dep outage.
    live = await app.liveness()
    assert live.status is HealthStatus.UP


@pytest.mark.asyncio
async def test_scenario_optional_cache_down_does_not_fail_readiness() -> None:
    app = BaseHealthProbe("api", debounce_s=0)
    app.register_dependency("primary_db", _Fixed("db", HealthStatus.UP))
    app.register_dependency(
        "warm_cache", _Fixed("cache", HealthStatus.DOWN),
        requirement=DependencyRequirement.OPTIONAL,
    )
    report = await app.readiness()
    assert report.status is HealthStatus.UP
    assert report.details["warm_cache.status"] == "down"


@pytest.mark.asyncio
async def test_scenario_degraded_dep_yields_degraded_readiness() -> None:
    app = BaseHealthProbe("api", debounce_s=0)
    app.register_dependency("broker", _Fixed("broker", HealthStatus.DEGRADED))
    report = await app.readiness()
    assert report.status is HealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_scenario_concurrent_dependency_checks_parallel() -> None:
    # Ten deps, each ~50ms — sequential ≥ 500ms. Concurrent should be ~50ms.
    class Slow:
        def __init__(self, name: str) -> None:
            self.name = name

        async def liveness(self) -> HealthReport:
            await asyncio.sleep(0.05)
            return HealthReport(HealthStatus.UP)

        async def readiness(self) -> HealthReport:
            await asyncio.sleep(0.05)
            return HealthReport(HealthStatus.UP)

        def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
            raise NotImplementedError

    app = BaseHealthProbe("api", timeout_s=2.0, debounce_s=0)
    for i in range(10):
        app.register_dependency(f"d{i}", Slow(f"d{i}"))
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    report = await app.readiness()
    elapsed = loop.time() - t0
    assert report.status is HealthStatus.UP
    assert elapsed < 0.35  # parallel, not sequential (< 500ms - slack)


@pytest.mark.asyncio
async def test_scenario_registry_aggregation() -> None:
    reg = HealthProbeRegistry()
    a = BaseHealthProbe("a", debounce_s=0)
    b = BaseHealthProbe("b", debounce_s=0)
    b.register_dependency("db", _Fixed("db", HealthStatus.DOWN))
    reg.register(a)
    reg.register(b)
    agg = await reg.aggregate_readiness()
    assert agg.status is HealthStatus.DOWN
    assert agg.details["b.status"] == "down"
    assert agg.details["a.status"] == "up"
    # Liveness aggregates each probe's OWN liveness — all UP.
    live = await reg.aggregate_liveness()
    assert live.status is HealthStatus.UP


@pytest.mark.asyncio
async def test_scenario_debounce_absorbs_single_blip() -> None:
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    app = BaseHealthProbe("api", debounce_s=10.0, now_fn=now)
    current = {"s": HealthStatus.UP}

    class Flap:
        name = "flap"

        async def liveness(self) -> HealthReport:
            return HealthReport(current["s"])

        async def readiness(self) -> HealthReport:
            return HealthReport(current["s"])

        def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
            raise NotImplementedError

    app.register_dependency("flap", Flap())
    assert (await app.readiness()).status is HealthStatus.UP
    # Blip within the debounce window — held as UP.
    current["s"] = HealthStatus.DOWN
    clock["t"] = 1.0
    assert (await app.readiness()).status is HealthStatus.UP
    # Recovery within window — back to UP cleanly.
    current["s"] = HealthStatus.UP
    clock["t"] = 2.0
    assert (await app.readiness()).status is HealthStatus.UP


@pytest.mark.asyncio
async def test_scenario_hot_path_is_fast() -> None:
    app = BaseHealthProbe("api", debounce_s=0)
    for i in range(20):
        app.register_dependency(f"d{i}", _Fixed(f"d{i}", HealthStatus.UP))
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    for _ in range(50):
        await app.readiness()
    elapsed = loop.time() - t0
    # 50 aggregations × 20 deps each — well under 1s on a reasonable CI box.
    assert elapsed < 1.0
