"""SamplingPolicy primitive — head-based sampling decisions.

**Scope note:** this primitive implements HEAD-BASED sampling only. Tail-based
sampling (observing full traces then deciding to keep/drop) requires a
separate collector-side buffer and is explicitly OUT OF SCOPE. The contract
previously spoke of a tail-based invariant; that language has been removed
since no tail logic exists in the impl. If you need tail decisions, compose
this primitive with a collector that buffers spans until commit.

Invariant IDs:

- SAMP-INV-01: when parent sampled, children MUST inherit unless the policy declares
  itself parent-overriding.
- SAMP-INV-02: decisions SHALL be deterministic per trace_id.
- SAMP-INV-03: probabilistic sampling MUST use trace_id hash modulo rate, NEVER
  per-span random draw.
- SAMP-INV-04: policies CANNOT raise; a failing policy SHALL fall back to default
  deny + internal counter.
- SAMP-INV-05: description() returns stable human-readable string, NEVER includes
  secret keys or cardinality-exploding values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

MAX_DESCRIPTION_LEN: Final[int] = 200


class SamplingInvariantError(ValueError):
    """Runtime invariant violation on a sampling decision."""


@dataclass(frozen=True)
class SamplingDecision:
    sampled: bool
    attributes: Mapping[str, str]
    trace_state: str | None


@runtime_checkable
class SamplingPolicy(Protocol):
    def should_sample(
        self,
        *,
        parent_context: object | None,
        trace_id: str,
        name: str,
        kind: str,
        attributes: Mapping[str, object],
        links: Sequence[object],
    ) -> SamplingDecision: ...

    def description(self) -> str: ...


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------
def _trace_id_bucket(trace_id: str) -> float:
    """SAMP-INV-03: deterministic bucket from trace_id hash."""
    if not trace_id or not isinstance(trace_id, str):
        return 1.0
    # Use last 8 hex digits → 32-bit unsigned int → [0, 1).
    try:
        n = int(trace_id[-8:], 16)
    except ValueError:
        return 1.0
    return n / 0xFFFFFFFF


class ParentBasedHeadSampler:
    """Head-based probabilistic sampler honoring parent sampled flag."""

    def __init__(self, head_ratio: float, *, parent_override: bool = False) -> None:
        if not 0.0 <= head_ratio <= 1.0:
            raise SamplingInvariantError("head_ratio MUST be in [0.0, 1.0].")
        self._ratio = head_ratio
        self._parent_override = parent_override
        self._fallback_count = 0

    def should_sample(
        self,
        *,
        parent_context: object | None,
        trace_id: str,
        name: str,
        kind: str,
        attributes: Mapping[str, object],
        links: Sequence[object],
    ) -> SamplingDecision:
        try:
            parent_sampled = False
            if parent_context is not None:
                # Attempt duck-typed access; if it raises, fall back.
                if hasattr(parent_context, "get") or isinstance(parent_context, dict):
                    parent_sampled = bool(parent_context.get("sampled"))
            if not self._parent_override and parent_sampled:
                return SamplingDecision(True, {"sampler.reason": "parent"}, None)
            bucket = _trace_id_bucket(trace_id)
            sampled = bucket < self._ratio
            return SamplingDecision(
                sampled, {"sampler.reason": "head"}, None
            )
        except Exception:  # noqa: BLE001 — SAMP-INV-04: never raise
            self._fallback_count += 1
            return SamplingDecision(False, {"sampler.reason": "fallback-deny"}, None)

    def description(self) -> str:
        desc = f"parent_based_head(ratio={self._ratio}, override={self._parent_override})"
        return desc[:MAX_DESCRIPTION_LEN]

    @property
    def fallback_count(self) -> int:
        return self._fallback_count


class AlwaysOnSampler:
    """Accept every span."""

    def should_sample(
        self,
        *,
        parent_context: object | None,
        trace_id: str,
        name: str,
        kind: str,
        attributes: Mapping[str, object],
        links: Sequence[object],
    ) -> SamplingDecision:
        return SamplingDecision(True, {"sampler.reason": "always-on"}, None)

    def description(self) -> str:
        return "always_on"


class AlwaysOffSampler:
    """Drop every span — default fallback."""

    def should_sample(
        self,
        *,
        parent_context: object | None,
        trace_id: str,
        name: str,
        kind: str,
        attributes: Mapping[str, object],
        links: Sequence[object],
    ) -> SamplingDecision:
        return SamplingDecision(False, {"sampler.reason": "always-off"}, None)

    def description(self) -> str:
        return "always_off"


__all__ = [
    "MAX_DESCRIPTION_LEN",
    "AlwaysOffSampler",
    "AlwaysOnSampler",
    "ParentBasedHeadSampler",
    "SamplingDecision",
    "SamplingInvariantError",
    "SamplingPolicy",
]
