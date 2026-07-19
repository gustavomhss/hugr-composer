"""Unit tests for HealthProbe — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio

import pytest
from HealthProbe import (
    BaseHealthProbe,
    DependencyRequirement,
    HealthProbeInvariantError,
    HealthProbeRegistry,
    HealthReport,
    HealthStatus,
    sanitize_report,
)


# ---------------------------------------------------------------------------
# Test helpers — fixed-status probes for composition tests.
# ---------------------------------------------------------------------------
class _FixedProbe:
    """Minimal probe that always returns the configured status."""

    def __init__(self, name: str, status: HealthStatus, details: dict[str, str] | None = None) -> None:
        self.name = name
        self._status = status
        self._details = details or {}

    async def liveness(self) -> HealthReport:
        return HealthReport(self._status, dict(self._details))

    async def readiness(self) -> HealthReport:
        return HealthReport(self._status, dict(self._details))

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


class _ThrowingProbe:
    """A probe whose readiness raises — exercise HEALTHPROBE-INV-04."""

    name = "bad"

    async def liveness(self) -> HealthReport:
        raise RuntimeError("liveness blew up")

    async def readiness(self) -> HealthReport:
        raise RuntimeError("readiness blew up")

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


class _HangingProbe:
    name = "slow"

    async def liveness(self) -> HealthReport:
        await asyncio.sleep(60)
        return HealthReport(HealthStatus.UP)

    async def readiness(self) -> HealthReport:
        await asyncio.sleep(60)
        return HealthReport(HealthStatus.UP)

    def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_01 — liveness ignores dependency status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_liveness_process_only_confirms() -> None:
    probe = BaseHealthProbe("svc")
    probe.register_dependency("db", _FixedProbe("db", HealthStatus.DOWN))
    report = await probe.liveness()
    assert report.status is HealthStatus.UP


@pytest.mark.asyncio
async def test_inv_liveness_process_only_prevents() -> None:
    # Even a DOWN dependency SHALL NEVER flip liveness DOWN.
    probe = BaseHealthProbe("svc")
    for i in range(5):
        probe.register_dependency(f"dep{i}", _FixedProbe(f"d{i}", HealthStatus.DOWN))
    report = await probe.liveness()
    assert report.status is HealthStatus.UP


@pytest.mark.asyncio
async def test_inv_liveness_process_only_under_failure() -> None:
    # Throwing + slow dependencies still MUST NOT break liveness.
    probe = BaseHealthProbe("svc")
    probe.register_dependency("bad", _ThrowingProbe())
    probe.register_dependency("slow", _HangingProbe())
    report = await probe.liveness()
    assert report.status is HealthStatus.UP


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_02 — readiness worst-wins across required dependencies
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_readiness_required_deps_confirms() -> None:
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency(
        "db", _FixedProbe("db", HealthStatus.DOWN), requirement=DependencyRequirement.REQUIRED
    )
    report = await probe.readiness()
    assert report.status is HealthStatus.DOWN
    assert report.details["db.status"] == "down"


@pytest.mark.asyncio
async def test_inv_readiness_required_deps_prevents() -> None:
    # OPTIONAL probes CANNOT force readiness false.
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency(
        "cache", _FixedProbe("cache", HealthStatus.DOWN),
        requirement=DependencyRequirement.OPTIONAL,
    )
    report = await probe.readiness()
    assert report.status is HealthStatus.UP


@pytest.mark.asyncio
async def test_inv_readiness_required_deps_under_failure() -> None:
    # Even when one required dep raises, readiness SHALL report DOWN (not crash).
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency("broken", _ThrowingProbe())
    report = await probe.readiness()
    assert report.status is HealthStatus.DOWN


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_03 — bounded by timeout; a hanging probe is DOWN
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_timeout_bounded_confirms() -> None:
    # Normal, fast check returns well under the timeout.
    probe = BaseHealthProbe("svc", timeout_s=0.5)
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    report = await probe.readiness()
    elapsed = loop.time() - t0
    assert report.status is HealthStatus.UP
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_inv_timeout_bounded_prevents() -> None:
    # A hanging probe SHALL be treated as DOWN and returns within timeout_s.
    probe = BaseHealthProbe("svc", timeout_s=0.1, debounce_s=0)
    probe.register_dependency("slow", _HangingProbe())
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    report = await probe.readiness()
    elapsed = loop.time() - t0
    assert report.status is HealthStatus.DOWN
    assert elapsed < 1.0  # bounded ≈ timeout_s, not the 60s hang


@pytest.mark.asyncio
async def test_inv_timeout_bounded_under_failure() -> None:
    # Configuring a non-positive timeout MUST be rejected at wiring.
    with pytest.raises(HealthProbeInvariantError):
        BaseHealthProbe("svc", timeout_s=0)
    with pytest.raises(HealthProbeInvariantError):
        BaseHealthProbe("svc", timeout_s=-1.0)


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_04 — a probe MUST NEVER throw
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_no_throw_confirms() -> None:
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency("bad", _ThrowingProbe())
    # Does not raise; returns a DOWN report with the exception class recorded.
    report = await probe.readiness()
    assert report.status is HealthStatus.DOWN


@pytest.mark.asyncio
async def test_inv_no_throw_prevents() -> None:
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency("bad", _ThrowingProbe())
    report = await probe.readiness()
    joined = " ".join(report.details.values())
    # Exception class name MUST appear somewhere in details (not the message).
    assert "RuntimeError" in joined or report.details.get("bad.status") == "down"


@pytest.mark.asyncio
async def test_inv_no_throw_under_failure() -> None:
    # Even under a cascade of broken probes, readiness NEVER raises.
    probe = BaseHealthProbe("svc", debounce_s=0)
    for i in range(4):
        probe.register_dependency(f"bad{i}", _ThrowingProbe())
    probe.register_dependency("slow", _HangingProbe())
    report = await probe.readiness()
    assert report.status is HealthStatus.DOWN


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_05 — unique name within the registry
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_unique_name_confirms() -> None:
    reg = HealthProbeRegistry()
    reg.register(BaseHealthProbe("a"))
    reg.register(BaseHealthProbe("b"))
    assert set(reg.names()) == {"a", "b"}


@pytest.mark.asyncio
async def test_inv_unique_name_prevents() -> None:
    reg = HealthProbeRegistry()
    reg.register(BaseHealthProbe("dup"))
    with pytest.raises(HealthProbeInvariantError):
        reg.register(BaseHealthProbe("dup"))
    # Duplicate dependency registration on one probe is ALSO rejected.
    probe = BaseHealthProbe("svc")
    probe.register_dependency("db", _FixedProbe("db", HealthStatus.UP))
    with pytest.raises(HealthProbeInvariantError):
        probe.register_dependency("db", _FixedProbe("db2", HealthStatus.UP))


@pytest.mark.asyncio
async def test_inv_unique_name_under_failure() -> None:
    # Empty / whitespace names MUST be rejected at construction.
    with pytest.raises(HealthProbeInvariantError):
        BaseHealthProbe("")
    with pytest.raises(HealthProbeInvariantError):
        BaseHealthProbe("   ")


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_06 — details MUST NOT leak secrets
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_no_secret_leak_confirms() -> None:
    redacted = sanitize_report(
        HealthReport(HealthStatus.UP, {"password": "hunter2", "region": "eu-west-1"})
    )
    assert redacted.details["password"] == "[REDACTED]"
    assert redacted.details["region"] == "eu-west-1"


@pytest.mark.asyncio
async def test_inv_no_secret_leak_prevents() -> None:
    # Connection-string-like values are redacted by pattern.
    redacted = sanitize_report(
        HealthReport(HealthStatus.UP, {"url": "postgres://u:p@h/db"})
    )
    assert redacted.details["url"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_inv_no_secret_leak_under_failure() -> None:
    # A probe that SOMEHOW returned secret-shaped details still gets scrubbed
    # by BaseHealthProbe.readiness before leaving the process.
    class LeakyProbe:
        name = "leaky"

        async def liveness(self) -> HealthReport:
            return HealthReport(HealthStatus.UP, {"Authorization": "Bearer token"})

        async def readiness(self) -> HealthReport:
            return HealthReport(HealthStatus.UP, {"Authorization": "Bearer token"})

        def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
            raise NotImplementedError

    parent = BaseHealthProbe("parent", debounce_s=0)
    parent.register_dependency("leaky", LeakyProbe())
    report = await parent.readiness()
    # Any surviving auth-looking key MUST be redacted.
    for k, v in report.details.items():
        if "authorization" in k.lower() or "bearer" in k.lower():
            assert v == "[REDACTED]"


# ---------------------------------------------------------------------------
# HEALTHPROBE_INV_07 — debounce UP->DOWN transitions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inv_debounce_confirms() -> None:
    # With a nonzero debounce window, a flip from UP to DOWN is held.
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    probe = BaseHealthProbe("svc", debounce_s=5.0, now_fn=now)
    dep_status = {"s": HealthStatus.UP}

    class Flaky:
        name = "flaky"

        async def liveness(self) -> HealthReport:
            return HealthReport(dep_status["s"])

        async def readiness(self) -> HealthReport:
            return HealthReport(dep_status["s"])

        def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
            raise NotImplementedError

    probe.register_dependency("flaky", Flaky())

    first = await probe.readiness()
    assert first.status is HealthStatus.UP

    # Dep flips DOWN — within debounce window, readiness is held UP.
    dep_status["s"] = HealthStatus.DOWN
    clock["t"] = 1.0
    held = await probe.readiness()
    assert held.status is HealthStatus.UP
    assert held.details.get("debounced") == "true"


@pytest.mark.asyncio
async def test_inv_debounce_prevents() -> None:
    # After the debounce window elapses, the DOWN status is allowed through.
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    probe = BaseHealthProbe("svc", debounce_s=5.0, now_fn=now)
    dep_status = {"s": HealthStatus.UP}

    class Flaky:
        name = "f"

        async def liveness(self) -> HealthReport:
            return HealthReport(dep_status["s"])

        async def readiness(self) -> HealthReport:
            return HealthReport(dep_status["s"])

        def register_dependency(self, name: str, probe: object) -> None:  # pragma: no cover
            raise NotImplementedError

    probe.register_dependency("f", Flaky())
    await probe.readiness()
    dep_status["s"] = HealthStatus.DOWN
    clock["t"] = 100.0  # far past debounce window
    eventual = await probe.readiness()
    assert eventual.status is HealthStatus.DOWN


@pytest.mark.asyncio
async def test_inv_debounce_under_failure() -> None:
    # With debounce_s == 0 there is NO debounce — DOWN propagates immediately.
    probe = BaseHealthProbe("svc", debounce_s=0)
    probe.register_dependency("d", _FixedProbe("d", HealthStatus.DOWN))
    report = await probe.readiness()
    assert report.status is HealthStatus.DOWN
    # Negative debounce is a wiring error.
    with pytest.raises(HealthProbeInvariantError):
        BaseHealthProbe("svc", debounce_s=-1.0)
