"""LoadShedder primitive — priority-aware admission control for overload regimes.

Implements the catalog Protocol for `resiliency.LoadShedder` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- LSH-INV-01: the shedder SHALL admit strictly by descending priority class and
  MUST NEVER admit a lower class while a higher class is being rejected.
- LSH-INV-02: a rejected request MUST surface an explicit overload signal
  (HTTP 503 / UNAVAILABLE) with a retry-after hint.
- LSH-INV-03: the cutoff priority CANNOT change more than once per
  `control_interval_ms` to prevent oscillation (hysteresis).
- LSH-INV-04: a request that passed admission control SHALL NEVER be shed
  later in the pipeline — `admit()` is the single, authoritative gate.
- LSH-INV-05: the shedder MUST publish the current cutoff as a metric so
  clients can cooperate with exponential backoff.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Priority taxonomy (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
Priority = Literal["critical", "normal", "sheddable_plus", "sheddable"]

# Rank mapping: LOWER rank = HIGHER priority (critical is the most important).
# A cutoff class C means: admit every class with rank(class) <= rank(C).
_PRIORITY_RANK: Final[dict[str, int]] = {
    "critical": 0,
    "normal": 1,
    "sheddable_plus": 2,
    "sheddable": 3,
}

# Ordered list used for table-driven operations and for choosing a more or
# less aggressive cutoff.
_PRIORITIES_BY_RANK: Final[tuple[Priority, ...]] = (
    "critical",
    "normal",
    "sheddable_plus",
    "sheddable",
)

# The FULL-OPEN cutoff admits every class (nothing is shed).
_CUTOFF_FULL_OPEN: Final[Priority] = "sheddable"
# The FULL-SHED cutoff admits only the most-critical class.
_CUTOFF_FULL_SHED: Final[Priority] = "critical"


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class LoadShedder(Protocol):
    def admit(self, priority: Priority, queue_depth: int, cpu_load_ewma: float) -> bool: ...
    def current_cutoff(self) -> Priority: ...
    def shed_rate(self) -> float: ...


# ---------------------------------------------------------------------------
# Overload-signal payload (LSH-INV-02)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RejectionSignal:
    """Explicit overload signal returned alongside every rejection.

    LSH-INV-02: every rejected request MUST surface this structure so callers
    can emit HTTP 503 / status UNAVAILABLE with a concrete `Retry-After` hint.
    The fields are serialisable and framework-agnostic.
    """

    http_status: int = 503
    grpc_status: str = "UNAVAILABLE"
    retry_after_seconds: float = 1.0
    reason: str = "load_shed"
    current_cutoff: Priority = _CUTOFF_FULL_OPEN


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class LoadShedderInvariantError(RuntimeError):
    """Raised when a LoadShedder invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Pluggable signal composition (extension contract)
# ---------------------------------------------------------------------------
CompositionAdapter = Callable[[float, float], float]


def compose_max(cpu: float, queue_norm: float) -> float:
    """`max` composition — the default; drives cutoff by the worst signal."""
    return max(cpu, queue_norm)


def compose_ewma(cpu: float, queue_norm: float) -> float:
    """Simple equal-weight average — smoother than `max`."""
    return (cpu + queue_norm) * 0.5


def compose_quantile(cpu: float, queue_norm: float) -> float:
    """Quantile-ish — weight the worse signal more heavily."""
    hi = max(cpu, queue_norm)
    lo = min(cpu, queue_norm)
    return hi * 0.75 + lo * 0.25


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
_DEFAULT_QUEUE_SATURATION: Final[int] = 100
_DEFAULT_CONTROL_INTERVAL_MS: Final[int] = 100
_DEFAULT_SHED_WINDOW_SIZE: Final[int] = 512

# Pressure band → cutoff index. Pressure is a 0..1 float composed from the
# signals via a `CompositionAdapter`. The band boundaries are declarative and
# always chosen so that higher pressure ⇒ a MORE aggressive cutoff (lower
# rank), satisfying LSH-INV-01.
_PRESSURE_BANDS: Final[tuple[tuple[float, int], ...]] = (
    # (pressure_threshold, cutoff_rank_inclusive)
    (0.95, 0),  # extreme overload → admit only critical
    (0.85, 1),  # heavy overload   → admit critical + normal
    (0.70, 2),  # warm             → admit critical + normal + sheddable_plus
    (0.00, 3),  # healthy          → admit everything
)


@dataclass
class _ShedWindow:
    """Rolling-window counter for shed_rate()."""

    size: int = _DEFAULT_SHED_WINDOW_SIZE
    admitted: int = 0
    rejected: int = 0
    samples: list[bool] = field(default_factory=list)

    def record(self, admitted_flag: bool) -> None:
        self.samples.append(admitted_flag)
        if admitted_flag:
            self.admitted += 1
        else:
            self.rejected += 1
        if len(self.samples) > self.size:
            evicted = self.samples.pop(0)
            if evicted:
                self.admitted -= 1
            else:
                self.rejected -= 1

    def rate(self) -> float:
        total = self.admitted + self.rejected
        if total == 0:
            return 0.0
        return self.rejected / total


class InMemoryLoadShedder:
    """Reference priority-aware load shedder.

    The shedder exposes the exact three-method catalog surface (`admit`,
    `current_cutoff`, `shed_rate`) and enforces every declared invariant at
    runtime. It is thread-safe — every mutation is guarded by a single
    internal lock so concurrent `admit()` calls from worker threads CANNOT
    race on the cutoff transition logic (LSH-INV-01, LSH-INV-03).
    """

    def __init__(
        self,
        *,
        control_interval_ms: int = _DEFAULT_CONTROL_INTERVAL_MS,
        queue_saturation: int = _DEFAULT_QUEUE_SATURATION,
        composition: CompositionAdapter = compose_max,
        clock: Callable[[], float] | None = None,
        metric_sink: Callable[[str, float, dict[str, str]], None] | None = None,
        window_size: int = _DEFAULT_SHED_WINDOW_SIZE,
    ) -> None:
        if control_interval_ms <= 0:
            raise ValueError("control_interval_ms must be > 0")
        if queue_saturation <= 0:
            raise ValueError("queue_saturation must be > 0")
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        self._control_interval_s: float = control_interval_ms / 1000.0
        self._queue_saturation: int = queue_saturation
        self._composition: CompositionAdapter = composition
        self._clock: Callable[[], float] = clock or time.monotonic
        self._metric_sink: Callable[[str, float, dict[str, str]], None] | None = metric_sink
        self._cutoff: Priority = _CUTOFF_FULL_OPEN
        # Seed "last change" one full control-interval in the past so the
        # FIRST cutoff transition is never debounced away by LSH-INV-03.
        self._cutoff_changed_at: float = self._clock() - self._control_interval_s
        self._window = _ShedWindow(size=window_size)
        self._lock = threading.Lock()
        self._admit_count: int = 0
        self._reject_count: int = 0
        # LSH-INV-04 provenance: every admitted decision is sealed via a
        # monotonic token so downstream pipeline code can assert that the
        # primitive never "re-decides" on a request post-admission.
        self._token_seq: int = 0
        # LSH-INV-05: publish cutoff at construction time.
        self._publish_cutoff_metric()

    # ------------------------------------------------------------------ API
    def admit(self, priority: Priority, queue_depth: int, cpu_load_ewma: float) -> bool:
        """Core admission decision. See LSH-INV-01 / -03 / -04.

        Accepts the catalog-declared signal shape and returns True iff the
        caller's priority class is at or above the current cutoff.
        """
        if priority not in _PRIORITY_RANK:
            raise LoadShedderInvariantError(
                f"LSH-INV-01: unknown priority '{priority}'; must be one of {_PRIORITIES_BY_RANK}."
            )
        if queue_depth < 0:
            raise ValueError("queue_depth must be >= 0")
        # Clamp CPU to [0, 1] defensively — an upstream signal provider may
        # over-report; clamping preserves LSH-INV-01 monotonicity.
        cpu_clamped = max(0.0, min(1.0, cpu_load_ewma))
        queue_norm = min(1.0, queue_depth / float(self._queue_saturation))
        pressure = max(0.0, min(1.0, self._composition(cpu_clamped, queue_norm)))

        with self._lock:
            self._maybe_update_cutoff(pressure)
            cutoff = self._cutoff
            # LSH-INV-01: admit strictly by descending priority.
            admitted = _PRIORITY_RANK[priority] <= _PRIORITY_RANK[cutoff]
            self._window.record(admitted)
            if admitted:
                self._admit_count += 1
                self._token_seq += 1
            else:
                self._reject_count += 1
        return admitted

    def current_cutoff(self) -> Priority:
        """LSH-INV-05: publish the current cutoff priority."""
        with self._lock:
            return self._cutoff

    def shed_rate(self) -> float:
        """Rolling shed rate over the most recent window (0.0 .. 1.0)."""
        with self._lock:
            return self._window.rate()

    # ------------------------------------------------------------------ introspection helpers
    @property
    def admitted_total(self) -> int:
        with self._lock:
            return self._admit_count

    @property
    def rejected_total(self) -> int:
        with self._lock:
            return self._reject_count

    def rejection_signal(self) -> RejectionSignal:
        """LSH-INV-02: structured overload signal for every rejected request."""
        with self._lock:
            return RejectionSignal(
                http_status=503,
                grpc_status="UNAVAILABLE",
                retry_after_seconds=max(0.1, self._control_interval_s),
                reason="load_shed",
                current_cutoff=self._cutoff,
            )

    # ------------------------------------------------------------------ internals
    def _maybe_update_cutoff(self, pressure: float) -> None:
        """Compute desired cutoff and apply it honouring LSH-INV-03."""
        desired_rank = _PRESSURE_BANDS[-1][1]
        for threshold, rank in _PRESSURE_BANDS:
            if pressure >= threshold:
                desired_rank = rank
                break
        desired = _PRIORITIES_BY_RANK[desired_rank]
        if desired == self._cutoff:
            return
        now = self._clock()
        if (now - self._cutoff_changed_at) < self._control_interval_s:
            # LSH-INV-03: refuse to oscillate — keep the current cutoff.
            return
        self._cutoff = desired
        self._cutoff_changed_at = now
        self._publish_cutoff_metric()

    def _publish_cutoff_metric(self) -> None:
        """LSH-INV-05: emit the current cutoff through the metric sink."""
        if self._metric_sink is None:
            return
        # LSH-INV-04: metric sinks MUST NEVER break the admission path. A
        # would-be admitted request SHALL NEVER be retroactively shed because
        # telemetry blew up — so we suppress any sink exception here.
        with contextlib.suppress(Exception):
            self._metric_sink(
                "load_shedder.current_cutoff",
                float(_PRIORITY_RANK[self._cutoff]),
                {"cutoff": self._cutoff},
            )


# ---------------------------------------------------------------------------
# Sealed-admit helper (LSH-INV-04 enforcement surface)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AdmissionToken:
    """Proof-of-admission issued by `SealedAdmit.admit`.

    LSH-INV-04: once a request holds a token, downstream pipeline stages
    MUST NOT consult the shedder again; the token is the single authoritative
    admission artefact. The pipeline helper below demonstrates the pattern
    callers should adopt in real deployments.
    """

    token_id: int
    priority: Priority
    cutoff_at_admit: Priority


class SealedAdmit:
    """Thin wrapper that turns `admit()` into a typed token (LSH-INV-04).

    Downstream stages receive an `AdmissionToken | None`; they MUST NOT call
    back into the shedder for the same request. The helper refuses to re-shed
    a token it already issued.
    """

    def __init__(self, shedder: InMemoryLoadShedder) -> None:
        self._shedder = shedder
        self._issued: set[int] = set()
        self._lock = threading.Lock()

    def admit(self, priority: Priority, queue_depth: int, cpu_load_ewma: float) -> AdmissionToken | None:
        admitted = self._shedder.admit(priority, queue_depth, cpu_load_ewma)
        if not admitted:
            return None
        with self._lock:
            # Read the seq assigned by the shedder — monotonic, unique.
            tid = self._shedder.admitted_total
            self._issued.add(tid)
            return AdmissionToken(
                token_id=tid,
                priority=priority,
                cutoff_at_admit=self._shedder.current_cutoff(),
            )

    def pass_through(self, token: AdmissionToken) -> None:
        """LSH-INV-04: downstream stages call this to confirm a token.

        Raises if the token was never issued (or was fabricated). ALWAYS
        returns None — an issued token is NEVER shed at this stage.
        """
        with self._lock:
            if token.token_id not in self._issued:
                raise LoadShedderInvariantError(
                    "LSH-INV-04: fabricated AdmissionToken — downstream SHALL NEVER "
                    "re-decide admission; only tokens issued by SealedAdmit pass through."
                )


__all__ = [
    "AdmissionToken",
    "CompositionAdapter",
    "InMemoryLoadShedder",
    "LoadShedder",
    "LoadShedderInvariantError",
    "Priority",
    "RejectionSignal",
    "SealedAdmit",
    "compose_ewma",
    "compose_max",
    "compose_quantile",
]
