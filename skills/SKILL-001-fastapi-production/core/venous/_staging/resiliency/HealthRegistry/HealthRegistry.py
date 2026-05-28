from __future__ import annotations
from collections.abc import Callable
from collections.abc import Coroutine
from typing import Any
import asyncio
import time


class HealthRegistry:
    """Singleton registry for async health-check functions.

    Args:
        timeout_ms: Default per-check timeout in milliseconds.
    """

    def __init__(self, timeout_ms: int=5000) -> None:
        self._checks: dict[str, dict[str, Any]] = {}
        self._failure_counts: dict[str, int] = {}
        self.timeout_ms = timeout_ms

    def register_check(self, name: str, check_fn: Callable[[], Coroutine[Any, Any, DependencyCheck]], *, critical: bool=False) -> None:
        """Register a named async check.

        Args:
            name: Unique check name (e.g. 'database', 'redis').
            check_fn: Async callable returning a DependencyCheck.
            critical: When True, failure blocks readiness probe.
        """
        self._checks[name] = {'fn': check_fn, 'critical': critical}
        self._failure_counts.setdefault(name, 0)

    async def _run_one(self, name: str) -> DependencyCheck:
        """Execute a single check with timeout and circuit-breaker logic.

        Args:
            name: Registered check name.

        Returns:
            DependencyCheck with status/latency/details.
        """
        entry = self._checks[name]
        t0 = time.monotonic()
        try:
            result: DependencyCheck = await asyncio.wait_for(entry['fn'](), timeout=self.timeout_ms / 1000)
            self._failure_counts[name] = 0
            return result
        except asyncio.TimeoutError:
            self._failure_counts[name] += 1
            lat = int((time.monotonic() - t0) * 1000)
            logger.warning("Health check '%s' timed out after %d ms", name, lat)
            status = self._circuit_status(name)
            return DependencyCheck(name=name, status=status, latency_ms=lat, details={'error': 'timeout'})
        except Exception as exc:
            self._failure_counts[name] += 1
            lat = int((time.monotonic() - t0) * 1000)
            logger.warning("Health check '%s' raised: %s", name, exc, exc_info=True)
            status = self._circuit_status(name)
            return DependencyCheck(name=name, status=status, latency_ms=lat, details={'error': str(exc)})

    def _circuit_status(self, name: str) -> HealthStatus:
        """Return 'degraded' after threshold, else 'unhealthy'.

        Args:
            name: Check name to inspect.
        """
        if self._failure_counts.get(name, 0) >= _CIRCUIT_BREAKER_THRESHOLD:
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY

    async def run_all(self) -> HealthReport:
        """Run every registered check and return a full HealthReport."""
        results = await asyncio.gather(*[self._run_one(n) for n in self._checks], return_exceptions=False)
        checks = list(results)
        overall = _aggregate_status(checks)
        return HealthReport(status=overall, checks=checks)

    async def run_readiness(self) -> HealthReport:
        """Run only critical checks (for /health/ready probe)."""
        names = [n for n, e in self._checks.items() if e['critical']]
        results = await asyncio.gather(*[self._run_one(n) for n in names], return_exceptions=False)
        checks = list(results)
        overall = _aggregate_status(checks)
        return HealthReport(status=overall, checks=checks)

    async def run_liveness(self) -> HealthReport:
        """Liveness check — always healthy unless process is stuck."""
        return HealthReport(status=HealthStatus.HEALTHY, checks=[])
