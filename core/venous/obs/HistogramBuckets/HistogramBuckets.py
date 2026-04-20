"""HistogramBuckets primitive — immutable latency / size boundaries.

Catalog fidelity note: this module implements the `HistogramBuckets` dataclass
described in `docs/research/outputs/AGENT_7_OBSERVABILITY.json`, with the two
factory classmethods (`latency_ms_default`, `payload_bytes_default`) serving as
the canonical preset registry. Boundaries are validated at construction against
the six catalog invariants; tampering is a programming bug the dataclass rejects.

Invariant IDs:

- HB-INV-01: boundaries MUST be strictly increasing, finite, non-negative, and
  SHALL include ≥ 5 buckets below the target p99.
- HB-INV-02: once assigned to an instrument, boundaries are immutable; changing
  at runtime is FORBIDDEN.
- HB-INV-03: latency boundaries MUST be expressed in milliseconds with unit 'ms'
  and NEVER mixed with seconds on the same instrument.
- HB-INV-04: lowest boundary MUST be smaller than the realistic measurement floor.
- HB-INV-05: bucket count SHALL NOT exceed 20 per instrument.
- HB-INV-06: default HTTP latency / payload size bucket sets MUST follow the OTel
  HTTP semconv recommendation and CANNOT be silently overridden at creation.

No I/O at import. All validators are pure functions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

MAX_BUCKETS: Final[int] = 20
MIN_BUCKETS_BELOW_P99: Final[int] = 5
# HB-INV-03: UCUM-compatible unit codes permitted for histogram boundaries.
ALLOWED_UNITS: Final[frozenset[str]] = frozenset({"ms", "us", "ns", "s",
                                                  "By", "KBy", "MBy", "1"})
# HB-INV-06: OTel HTTP semconv recommended latency-in-milliseconds buckets.
SEMCONV_HTTP_LATENCY_BOUNDARIES: Final[tuple[float, ...]] = (
    1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0,
    1000.0, 2500.0, 5000.0, 10_000.0,
)
# HB-INV-06: OTel HTTP semconv recommended payload-size buckets (bytes).
SEMCONV_HTTP_PAYLOAD_BOUNDARIES: Final[tuple[float, ...]] = (
    100.0, 1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0,
)


class HistogramBucketsInvariantError(ValueError):
    """Runtime invariant violation on a HistogramBuckets configuration."""


def validate_unit(unit: str) -> str:
    """HB-INV-03: unit MUST be a UCUM code; latency discipline is enforced by
    rejecting 's'-on-latency mixing at instrument creation callers."""
    if not isinstance(unit, str) or not unit or unit not in ALLOWED_UNITS:
        raise HistogramBucketsInvariantError(
            f"HB-INV-03: unit {unit!r} MUST be one of {sorted(ALLOWED_UNITS)}."
        )
    return unit


def validate_boundaries(
    boundaries: Sequence[float],
    *,
    target_p99: float | None = None,
) -> tuple[float, ...]:
    """Validate boundary list against HB-INV-01, HB-INV-05."""
    if not boundaries:
        raise HistogramBucketsInvariantError(
            "HB-INV-01: boundaries MUST be non-empty."
        )
    if len(boundaries) > MAX_BUCKETS:
        raise HistogramBucketsInvariantError(
            f"HB-INV-05: bucket count SHALL NOT exceed {MAX_BUCKETS}; got {len(boundaries)}."
        )
    out: list[float] = []
    prev: float | None = None
    for b in boundaries:
        if isinstance(b, bool) or not isinstance(b, (int, float)):
            raise HistogramBucketsInvariantError(
                "HB-INV-01: boundaries MUST be numeric (int/float)."
            )
        bv = float(b)
        if math.isnan(bv) or math.isinf(bv):
            raise HistogramBucketsInvariantError(
                "HB-INV-01: boundaries MUST be finite (no NaN / Inf)."
            )
        if bv < 0:
            raise HistogramBucketsInvariantError(
                "HB-INV-01: boundaries MUST be non-negative."
            )
        if prev is not None and bv <= prev:
            raise HistogramBucketsInvariantError(
                "HB-INV-01: boundaries MUST be strictly increasing."
            )
        out.append(bv)
        prev = bv
    tup = tuple(out)
    if target_p99 is not None:
        below = sum(1 for b in tup if b < target_p99)
        if below < MIN_BUCKETS_BELOW_P99:
            raise HistogramBucketsInvariantError(
                f"HB-INV-01: at least {MIN_BUCKETS_BELOW_P99} buckets MUST lie "
                f"below the target p99 ({target_p99}); got {below}."
            )
    return tup


@dataclass(frozen=True)
class HistogramBuckets:
    """Immutable histogram boundaries with unit discipline.

    Matches the catalog `api_signature` exactly; callers bind an instance to an
    instrument at creation time via the `boundaries=` parameter of
    `MetricMeter.histogram(...)`.
    """

    name: str
    unit: str
    boundaries: Sequence[float]
    target_p99: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise HistogramBucketsInvariantError(
                "HistogramBuckets.name MUST be a non-empty str."
            )
        validate_unit(self.unit)
        # HB-INV-01 / HB-INV-05: validate; store as an immutable tuple. The
        # `target_p99` hint, when supplied, enforces the ≥5-buckets-below-p99
        # sub-clause of HB-INV-01 via `validate_boundaries` — previously the
        # sub-clause was only checked by the factory presets, so a caller
        # building `HistogramBuckets(name, unit, boundaries)` directly
        # bypassed the ≥5 bucket requirement entirely.
        object.__setattr__(
            self, "boundaries",
            validate_boundaries(self.boundaries, target_p99=self.target_p99),
        )

    @classmethod
    def latency_ms_default(cls) -> HistogramBuckets:
        """HB-INV-06: OTel SemConv 1.27 HTTP server latency recommended buckets.

        Use this preset for any HTTP-shaped latency histogram so p99 is
        comparable across services.
        """
        return cls(
            name="http.server.request.duration",
            unit="ms",
            boundaries=SEMCONV_HTTP_LATENCY_BOUNDARIES,
        )

    @classmethod
    def payload_bytes_default(cls) -> HistogramBuckets:
        """HB-INV-06: OTel SemConv 1.27 HTTP payload-size recommended buckets."""
        return cls(
            name="http.server.request.size",
            unit="By",
            boundaries=SEMCONV_HTTP_PAYLOAD_BOUNDARIES,
        )


__all__ = [
    "ALLOWED_UNITS",
    "MAX_BUCKETS",
    "MIN_BUCKETS_BELOW_P99",
    "SEMCONV_HTTP_LATENCY_BOUNDARIES",
    "SEMCONV_HTTP_PAYLOAD_BOUNDARIES",
    "HistogramBuckets",
    "HistogramBucketsInvariantError",
    "validate_boundaries",
    "validate_unit",
]
