"""MetricMeter primitive — OpenTelemetry-aligned instrument factory.

Catalog invariants enforced at runtime:

- METRIC-INV-01: Counter instruments MUST only accept non-negative values;
  negative deltas SHALL raise and are FORBIDDEN to be silently clamped.
- METRIC-INV-02: Histogram boundaries MUST be finite, strictly increasing,
  and immutable once the instrument is created.
- METRIC-INV-03: Instrument names MUST match '^[A-Za-z][A-Za-z0-9_./-]{0,62}$'
  per OTel specification and CANNOT collide with a differently-typed instrument.
- METRIC-INV-04: Every instrument MUST carry a UCUM unit string.
- METRIC-INV-05: Observable gauge callbacks MUST be idempotent in a collection
  cycle and SHALL NEVER raise.
- METRIC-INV-06: Attribute sets NEVER include unbounded-cardinality keys.

Zero I/O at import.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Final, Protocol, runtime_checkable

INSTRUMENT_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{0,62}$")
UCUM_ALLOWED_UNITS: Final[frozenset[str]] = frozenset(
    {"1", "ms", "s", "By", "KBy", "MBy", "GBy", "Hz", "%", "bit", "us", "ns", "min", "h"}
)
FORBIDDEN_CARDINALITY_KEYS: Final[frozenset[str]] = frozenset(
    {"user.id", "request.id", "http.url", "url.full", "enduser.id", "user_id", "request_id", "trace_id", "span_id"}
)


class MetricInvariantError(ValueError):
    """Runtime invariant violation on a metric instrument."""


# ---------------------------------------------------------------------------
# Protocol surface (mirrors catalog api_signature)
# ---------------------------------------------------------------------------
@runtime_checkable
class Counter(Protocol):
    def add(self, value: float, attributes: Mapping[str, str] | None = None) -> None: ...


@runtime_checkable
class UpDownCounter(Protocol):
    def add(self, value: float, attributes: Mapping[str, str] | None = None) -> None: ...


@runtime_checkable
class Histogram(Protocol):
    def record(self, value: float, attributes: Mapping[str, str] | None = None) -> None: ...


@runtime_checkable
class MetricMeter(Protocol):
    def counter(self, name: str, *, unit: str, description: str) -> Counter: ...
    def up_down_counter(self, name: str, *, unit: str, description: str) -> UpDownCounter: ...
    def histogram(
        self,
        name: str,
        *,
        unit: str,
        description: str,
        boundaries: Sequence[float] | None = None,
    ) -> Histogram: ...
    def observable_gauge(
        self,
        name: str,
        callback: Callable[[], float],
        *,
        unit: str,
        description: str,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Runtime validators
# ---------------------------------------------------------------------------
def validate_name(name: str) -> str:
    if not isinstance(name, str) or not INSTRUMENT_NAME_RE.match(name):
        raise MetricInvariantError(
            f"METRIC-INV-03: instrument name MUST match '{INSTRUMENT_NAME_RE.pattern}', got {name!r}."
        )
    return name


def validate_unit(unit: str) -> str:
    if not isinstance(unit, str) or not unit:
        raise MetricInvariantError("METRIC-INV-04: unit MUST be a non-empty UCUM string.")
    if unit not in UCUM_ALLOWED_UNITS:
        raise MetricInvariantError(
            f"METRIC-INV-04: unit {unit!r} is not in the allowed UCUM set. "
            f"Allowed: {sorted(UCUM_ALLOWED_UNITS)}. "
            f"Extend UCUM_ALLOWED_UNITS if a new unit is needed — do NOT "
            f"silently accept arbitrary strings."
        )
    return unit


def validate_boundaries(boundaries: Sequence[float]) -> tuple[float, ...]:
    if not boundaries:
        raise MetricInvariantError("METRIC-INV-02: histogram boundaries MUST be non-empty.")
    out: list[float] = []
    prev: float | None = None
    for b in boundaries:
        if not isinstance(b, (int, float)) or isinstance(b, bool):
            raise MetricInvariantError("METRIC-INV-02: boundaries MUST be numeric.")
        bv = float(b)
        if math.isnan(bv) or math.isinf(bv):
            raise MetricInvariantError("METRIC-INV-02: boundaries MUST be finite.")
        if prev is not None and bv <= prev:
            raise MetricInvariantError(
                "METRIC-INV-02: boundaries MUST be strictly increasing."
            )
        out.append(bv)
        prev = bv
    return tuple(out)


def validate_attributes(attrs: Mapping[str, str] | None) -> Mapping[str, str]:
    if attrs is None:
        return {}
    for key in attrs:
        if key in FORBIDDEN_CARDINALITY_KEYS:
            raise MetricInvariantError(
                f"METRIC-INV-06: attribute key {key!r} is FORBIDDEN (unbounded cardinality)."
            )
    return dict(attrs)


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------
class _CounterImpl:
    def __init__(self, name: str, unit: str, description: str) -> None:
        self.name = name
        self.unit = unit
        self.description = description
        self._lock = threading.Lock()
        self._measurements: list[tuple[float, Mapping[str, str]]] = []

    def add(self, value: float, attributes: Mapping[str, str] | None = None) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MetricInvariantError("METRIC-INV-01: value MUST be int or float.")
        if value < 0:
            raise MetricInvariantError(
                "METRIC-INV-01: Counter.add MUST reject negative values; "
                "silent clamping is FORBIDDEN."
            )
        attrs = validate_attributes(attributes)
        with self._lock:
            self._measurements.append((float(value), attrs))

    @property
    def measurements(self) -> Sequence[tuple[float, Mapping[str, str]]]:
        return tuple(self._measurements)


class _UpDownCounterImpl:
    def __init__(self, name: str, unit: str, description: str) -> None:
        self.name = name
        self.unit = unit
        self.description = description
        self._lock = threading.Lock()
        self._measurements: list[tuple[float, Mapping[str, str]]] = []

    def add(self, value: float, attributes: Mapping[str, str] | None = None) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MetricInvariantError("METRIC-INV-01 supporting: value MUST be numeric.")
        attrs = validate_attributes(attributes)
        with self._lock:
            self._measurements.append((float(value), attrs))


class _HistogramImpl:
    def __init__(self, name: str, unit: str, description: str,
                 boundaries: Sequence[float]) -> None:
        self.name = name
        self.unit = unit
        self.description = description
        self._boundaries: tuple[float, ...] = validate_boundaries(boundaries)
        self._lock = threading.Lock()
        self._measurements: list[tuple[float, Mapping[str, str]]] = []

    @property
    def boundaries(self) -> tuple[float, ...]:
        """METRIC-INV-02: immutable after creation."""
        return self._boundaries

    def record(self, value: float, attributes: Mapping[str, str] | None = None) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MetricInvariantError("value MUST be numeric.")
        attrs = validate_attributes(attributes)
        with self._lock:
            self._measurements.append((float(value), attrs))


class InMemoryMetricMeter:
    """Reference MetricMeter implementation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._instruments: dict[str, tuple[str, object]] = {}
        self._gauges: dict[str, Callable[[], float]] = {}

    def _register(self, name: str, kind: str, inst: object) -> None:
        with self._lock:
            if name in self._instruments:
                existing_kind, _ = self._instruments[name]
                if existing_kind != kind:
                    raise MetricInvariantError(
                        f"METRIC-INV-03: instrument {name!r} already registered as "
                        f"{existing_kind!r}; CANNOT collide with {kind!r}."
                    )
            self._instruments[name] = (kind, inst)

    def counter(self, name: str, *, unit: str, description: str) -> Counter:
        validate_name(name)
        validate_unit(unit)
        c = _CounterImpl(name, unit, description)
        self._register(name, "counter", c)
        return c

    def up_down_counter(self, name: str, *, unit: str, description: str) -> UpDownCounter:
        validate_name(name)
        validate_unit(unit)
        u = _UpDownCounterImpl(name, unit, description)
        self._register(name, "up_down_counter", u)
        return u

    def histogram(
        self,
        name: str,
        *,
        unit: str,
        description: str,
        boundaries: Sequence[float] | None = None,
    ) -> Histogram:
        validate_name(name)
        validate_unit(unit)
        bounds: Sequence[float] = tuple(boundaries) if boundaries else (1.0, 5.0, 10.0, 50.0, 100.0)
        h = _HistogramImpl(name, unit, description, bounds)
        self._register(name, "histogram", h)
        return h

    def observable_gauge(
        self,
        name: str,
        callback: Callable[[], float],
        *,
        unit: str,
        description: str,
    ) -> None:
        validate_name(name)
        validate_unit(unit)
        self._register(name, "observable_gauge", callback)
        self._gauges[name] = callback

    def collect_gauge(self, name: str) -> float | None:
        """METRIC-INV-05: callbacks SHALL NEVER raise; exceptions drop the measurement."""
        cb = self._gauges.get(name)
        if cb is None:
            return None
        try:
            return float(cb())
        except Exception:  # noqa: BLE001 — invariant: swallow and drop
            return None

    @property
    def instruments(self) -> Mapping[str, tuple[str, object]]:
        with self._lock:
            return dict(self._instruments)


__all__ = [
    "FORBIDDEN_CARDINALITY_KEYS",
    "INSTRUMENT_NAME_RE",
    "UCUM_ALLOWED_UNITS",
    "Counter",
    "Histogram",
    "InMemoryMetricMeter",
    "MetricInvariantError",
    "MetricMeter",
    "UpDownCounter",
    "validate_attributes",
    "validate_boundaries",
    "validate_name",
    "validate_unit",
]
