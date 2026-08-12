"""HealthProbe primitive — liveness / readiness signal for orchestrators.

Implements the merged Protocol documented in
`docs/research/COLLISIONS_RESOLVED.md` section 1 (co-produced by Agent 1
FRAMEWORKS and Agent 4 RESILIENCY). The module performs zero I/O at import.

Invariant IDs cited by this module:

- HEALTHPROBE-INV-01: liveness MUST only report DOWN when the process itself
  CANNOT make forward progress; a slow or failing dependency SHALL NEVER flip
  liveness DOWN.
- HEALTHPROBE-INV-02: readiness SHALL report DOWN when any required dependency
  reports DOWN; optional probes CANNOT force readiness false.
- HEALTHPROBE-INV-03: both liveness() and readiness() MUST complete within a
  declared timeout; a hanging probe SHALL be treated as DOWN.
- HEALTHPROBE-INV-04: a probe MUST NEVER throw; unexpected exceptions SHALL be
  caught and turned into DOWN with the exception class as a details entry.
- HEALTHPROBE-INV-05: name MUST be unique within the registry; duplicate
  registrations SHALL be rejected.
- HEALTHPROBE-INV-06: details MUST NOT leak secrets (connection strings,
  tokens, stack traces).
- HEALTHPROBE-INV-07: transitions from UP to DOWN SHALL be debounced by a
  configurable window to prevent routing-plane flapping.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Public types (mirror the canonical merged spec byte-for-byte)
# ---------------------------------------------------------------------------
class HealthStatus(str, Enum):
    """Three-valued health signal per k8s + SRE Workbook convention."""

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True)
class HealthReport:
    """Immutable, typed outcome of one probe invocation."""

    status: HealthStatus
    details: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class HealthProbe(Protocol):
    """Canonical Protocol — see COLLISIONS_RESOLVED.md §1."""

    name: str

    async def liveness(self) -> HealthReport: ...
    async def readiness(self) -> HealthReport: ...
    def register_dependency(self, name: str, probe: HealthProbe) -> None: ...


# ---------------------------------------------------------------------------
# Constants + secret redaction
# ---------------------------------------------------------------------------
# Heuristic secret patterns — HEALTHPROBE-INV-06. The probe CANNOT know every
# secret shape; it refuses the most common leakage vectors and the surface
# stays tiny (details is <name,str> by contract, no free-form blobs).
_SECRET_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "private_key",
        "client_secret",
        "access_key",
        "credential",
        "dsn",
        "connection_string",
    }
)
_SECRET_VALUE_RE: Final[re.Pattern[str]] = re.compile(
    # Connection strings and URLs with embedded credentials (scheme://user:pw@host).
    r"[a-zA-Z][a-zA-Z0-9+.-]*://[^:\s/]+:[^@\s/]+@",
)
_DEFAULT_TIMEOUT_S: Final[float] = 2.0
_DEFAULT_DEBOUNCE_S: Final[float] = 10.0


class HealthProbeInvariantError(ValueError):
    """Raised when a programmer-level invariant is violated (registration only).

    Note: runtime probe failures do NOT raise — they return DOWN
    (HEALTHPROBE-INV-04). This exception only signals mis-use at wiring time.
    """


# ---------------------------------------------------------------------------
# Secret-scrubbing guard (HEALTHPROBE-INV-06)
# ---------------------------------------------------------------------------
def _scrub_details(details: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of `details` with secret-shaped keys/values redacted."""
    out: dict[str, str] = {}
    for raw_key, raw_val in details.items():
        key = str(raw_key)
        val = str(raw_val)
        key_lc = key.lower()
        if any(tok in key_lc for tok in _SECRET_KEY_TOKENS):
            out[key] = "[REDACTED]"
            continue
        if _SECRET_VALUE_RE.search(val):
            out[key] = "[REDACTED]"
            continue
        out[key] = val
    return out


def sanitize_report(report: HealthReport) -> HealthReport:
    """Public helper — returns a new report with secrets redacted."""
    scrubbed = _scrub_details(report.details)
    if scrubbed == dict(report.details):
        return report
    return HealthReport(status=report.status, details=scrubbed)


# ---------------------------------------------------------------------------
# Base reference probe
# ---------------------------------------------------------------------------
#: Types of dependency registration. REQUIRED dependencies gate readiness;
#: OPTIONAL dependencies are informational only (HEALTHPROBE-INV-02).
class DependencyRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class _Registered:
    probe: HealthProbe
    requirement: DependencyRequirement


class BaseHealthProbe:
    """Reference implementation of the HealthProbe Protocol.

    Thread- and async-safe. Sub-classes override `_check_process_liveness`
    (cheap self-check) and `_check_local_readiness` (local readiness — e.g.
    warm-up complete). Dependency aggregation is performed by the base class.
    """

    name: str

    def __init__(
        self,
        name: str,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        debounce_s: float = _DEFAULT_DEBOUNCE_S,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise HealthProbeInvariantError(
                "HEALTHPROBE-INV-05 supporting: probe name MUST be non-empty string."
            )
        if timeout_s <= 0:
            raise HealthProbeInvariantError(
                "HEALTHPROBE-INV-03: timeout_s MUST be > 0."
            )
        if debounce_s < 0:
            raise HealthProbeInvariantError(
                "HEALTHPROBE-INV-07: debounce_s MUST be >= 0."
            )
        self.name = name
        self.timeout_s: float = timeout_s
        self.debounce_s: float = debounce_s
        self._deps: dict[str, _Registered] = {}
        self._now_fn: Callable[[], float] = now_fn or time.monotonic
        # HEALTHPROBE-INV-07 — last UP-observed moment per dependency (and self).
        self._last_up_at: dict[str, float] = {}
        # last observed status per key (for debounce decisions)
        self._last_status: dict[str, HealthStatus] = {}

    # -- Protocol: register_dependency ---------------------------------------
    def register_dependency(
        self,
        name: str,
        probe: HealthProbe,
        *,
        requirement: DependencyRequirement = DependencyRequirement.REQUIRED,
    ) -> None:
        """HEALTHPROBE-INV-05: reject duplicate registration by name."""
        if not isinstance(name, str) or not name.strip():
            raise HealthProbeInvariantError(
                "HEALTHPROBE-INV-05: dependency name MUST be non-empty string."
            )
        if name in self._deps:
            raise HealthProbeInvariantError(
                f"HEALTHPROBE-INV-05: duplicate dependency registration for name={name!r}."
            )
        if probe is self:
            raise HealthProbeInvariantError(
                "HEALTHPROBE-INV-05: a probe CANNOT register itself as its own dependency."
            )
        self._deps[name] = _Registered(probe=probe, requirement=requirement)

    # -- Override points -----------------------------------------------------
    async def _check_process_liveness(self) -> HealthReport:
        """Cheap self-test. Default: always UP (process is responsive)."""
        return HealthReport(HealthStatus.UP)

    async def _check_local_readiness(self) -> HealthReport:
        """Local readiness — e.g. warm-up complete. Default: UP."""
        return HealthReport(HealthStatus.UP)

    # -- Protocol: liveness --------------------------------------------------
    async def liveness(self) -> HealthReport:
        """HEALTHPROBE-INV-01: dependency health MUST NEVER flip liveness DOWN.

        Only the process's own ability to make progress matters.
        HEALTHPROBE-INV-03 + 04: wrapped in timeout + universal catch.
        """
        report = await _run_guarded(
            self._check_process_liveness,
            self.timeout_s,
            invariant_id="HEALTHPROBE-INV-01",
        )
        # Debounce on liveness too: avoids pointless restart loops on a single
        # blip (HEALTHPROBE-INV-07).
        final = self._apply_debounce("__self__", report)
        return HealthReport(
            status=final.status,
            details=_scrub_details(final.details),
        )

    # -- Protocol: readiness -------------------------------------------------
    async def readiness(self) -> HealthReport:
        """HEALTHPROBE-INV-02: worst-wins across REQUIRED dependencies."""
        local = await _run_guarded(
            self._check_local_readiness,
            self.timeout_s,
            invariant_id="HEALTHPROBE-INV-02",
        )
        details: dict[str, str] = {f"local.{k}": v for k, v in local.details.items()}
        details["local.status"] = local.status.value

        # Aggregate dependencies concurrently (HEALTHPROBE-INV-03).
        dep_names = list(self._deps.keys())
        dep_results = await asyncio.gather(
            *(
                _run_guarded(
                    self._deps[n].probe.readiness,
                    self.timeout_s,
                    invariant_id="HEALTHPROBE-INV-02",
                )
                for n in dep_names
            ),
            return_exceptions=False,
        )

        worst = local.status
        for dep_name, dep_report in zip(dep_names, dep_results, strict=True):
            entry = self._deps[dep_name]
            details[f"{dep_name}.status"] = dep_report.status.value
            if entry.requirement is DependencyRequirement.OPTIONAL:
                # HEALTHPROBE-INV-02: optional probes CANNOT force readiness false.
                continue
            worst = _worst_of(worst, dep_report.status)

        aggregated = HealthReport(status=worst, details=details)
        debounced = self._apply_debounce("__readiness__", aggregated)
        return HealthReport(
            status=debounced.status,
            details=_scrub_details(debounced.details),
        )

    # -- Debounce (HEALTHPROBE-INV-07) --------------------------------------
    def _apply_debounce(self, key: str, report: HealthReport) -> HealthReport:
        """Hold UP briefly before flipping to DOWN, per the configured window.

        If `debounce_s == 0` the report is returned unchanged.
        """
        now = self._now_fn()
        prev_status = self._last_status.get(key)
        if report.status is HealthStatus.UP:
            self._last_up_at[key] = now
            self._last_status[key] = HealthStatus.UP
            return report
        # report.status is DEGRADED or DOWN
        last_up_at = self._last_up_at.get(key)
        if (
            self.debounce_s > 0
            and prev_status is HealthStatus.UP
            and last_up_at is not None
            and (now - last_up_at) < self.debounce_s
        ):
            merged_details = dict(report.details)
            merged_details["debounced"] = "true"
            # Hold the UP signal for the debounce window.
            self._last_status[key] = HealthStatus.UP
            return HealthReport(status=HealthStatus.UP, details=merged_details)
        self._last_status[key] = report.status
        return report


# ---------------------------------------------------------------------------
# Utility: guarded async invocation (HEALTHPROBE-INV-03 + INV-04)
# ---------------------------------------------------------------------------
async def _run_guarded(
    coro_fn: Callable[[], Awaitable[HealthReport]],
    timeout_s: float,
    *,
    invariant_id: str,
) -> HealthReport:
    """Run `coro_fn` under a timeout; fold any failure into a DOWN report."""
    try:
        awaitable = coro_fn()
    except BaseException as exc:  # noqa: BLE001 — HEALTHPROBE-INV-04: swallow
        return HealthReport(
            status=HealthStatus.DOWN,
            details={
                "error.type": type(exc).__name__,
                "violated_invariant": invariant_id,
            },
        )
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError:
        return HealthReport(
            status=HealthStatus.DOWN,
            details={
                "error.type": "TimeoutError",
                "timeout_s": f"{timeout_s:.3f}",
                "violated_invariant": "HEALTHPROBE-INV-03",
            },
        )
    except BaseException as exc:  # noqa: BLE001 — HEALTHPROBE-INV-04: swallow
        return HealthReport(
            status=HealthStatus.DOWN,
            details={
                "error.type": type(exc).__name__,
                "violated_invariant": "HEALTHPROBE-INV-04",
            },
        )


_STATUS_RANK: Final[dict[HealthStatus, int]] = {
    HealthStatus.UP: 0,
    HealthStatus.DEGRADED: 1,
    HealthStatus.DOWN: 2,
}


def _worst_of(a: HealthStatus, b: HealthStatus) -> HealthStatus:
    """Return the worse of two HealthStatus values (UP < DEGRADED < DOWN)."""
    return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b


# ---------------------------------------------------------------------------
# Registry (HEALTHPROBE-INV-05 surface — app-level uniqueness)
# ---------------------------------------------------------------------------
class HealthProbeRegistry:
    """Process-wide registry of probes; enforces name uniqueness across probes."""

    def __init__(self) -> None:
        self._probes: dict[str, HealthProbe] = {}

    def register(self, probe: HealthProbe) -> None:
        if not isinstance(probe.name, str) or not probe.name.strip():
            raise HealthProbeInvariantError(
                "HEALTHPROBE-INV-05: registered probe MUST expose a non-empty name."
            )
        if probe.name in self._probes:
            raise HealthProbeInvariantError(
                f"HEALTHPROBE-INV-05: duplicate probe name={probe.name!r} in registry."
            )
        self._probes[probe.name] = probe

    def get(self, name: str) -> HealthProbe:
        return self._probes[name]

    def names(self) -> tuple[str, ...]:
        return tuple(self._probes)

    async def aggregate_readiness(self) -> HealthReport:
        """Worst-wins aggregation across every registered probe."""
        if not self._probes:
            return HealthReport(HealthStatus.UP, details={"probes": "0"})
        names = list(self._probes)
        reports = await asyncio.gather(*(self._probes[n].readiness() for n in names))
        worst = HealthStatus.UP
        details: dict[str, str] = {}
        for n, r in zip(names, reports, strict=True):
            details[f"{n}.status"] = r.status.value
            worst = _worst_of(worst, r.status)
        return HealthReport(status=worst, details=_scrub_details(details))

    async def aggregate_liveness(self) -> HealthReport:
        """HEALTHPROBE-INV-01: liveness aggregates each probe's own liveness.

        A single probe reporting DOWN makes the process liveness DOWN — that
        probe's own process-level health is broken. This does NOT include
        dependency readiness (by construction of per-probe `liveness()`).
        """
        if not self._probes:
            return HealthReport(HealthStatus.UP, details={"probes": "0"})
        names = list(self._probes)
        reports = await asyncio.gather(*(self._probes[n].liveness() for n in names))
        worst = HealthStatus.UP
        details: dict[str, str] = {}
        for n, r in zip(names, reports, strict=True):
            details[f"{n}.status"] = r.status.value
            worst = _worst_of(worst, r.status)
        return HealthReport(status=worst, details=_scrub_details(details))


__all__ = [
    "BaseHealthProbe",
    "DependencyRequirement",
    "HealthProbe",
    "HealthProbeInvariantError",
    "HealthProbeRegistry",
    "HealthReport",
    "HealthStatus",
    "sanitize_report",
]
