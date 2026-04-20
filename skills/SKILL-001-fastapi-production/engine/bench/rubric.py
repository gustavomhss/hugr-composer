"""Scoring rubric — CONTRACT §B3.2.

Four dimensions, 25% each:

1. **scaffold_completeness** — does the produced codebase cover every
   requirement in the spec? Checked mechanically (keywords in spec map
   to files/endpoints/tables present) + auditor sign-off for semantics.
2. **test_suite_pass** — percentage of the spec's acceptance criteria
   covered by passing tests in the produced codebase.
3. **primitive_gate_pass** — for every primitive the Maestro imported,
   does the primitive still pass its T0-T9 gate in isolation? Regression
   guard that the Maestro did not corrupt a primitive.
4. **hand_editability** — a human reader's 0-100 rating of how easy the
   produced codebase is to fork and edit. Judged on: naming, module
   boundaries, lack of magic, test readability. Provided at scoring
   time as an integer 0-100.

The overall score is the arithmetic mean of the four dimensions, each
normalized to 0-100. `score_spec` returns a `SpecScore` dataclass with
the breakdown; `aggregate` over many specs is the north-star number.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class DimensionScore:
    name: str
    value: float           # 0-100
    evidence: str          # short, reviewable

    def weighted(self) -> float:
        return self.value * 0.25


@dataclass(frozen=True)
class SpecScore:
    spec_id: str
    tier: str              # baseline / mid / adversarial
    dimensions: tuple[DimensionScore, ...]

    @property
    def total(self) -> float:
        return sum(d.weighted() for d in self.dimensions)

    def as_dict(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "tier": self.tier,
            "total": round(self.total, 2),
            "dimensions": [asdict(d) for d in self.dimensions],
        }


def score_spec(
    spec_id: str,
    tier: str,
    *,
    scaffold_completeness: float,
    test_suite_pass: float,
    primitive_gate_pass: float,
    hand_editability: float,
    evidence: dict[str, str] | None = None,
) -> SpecScore:
    """Build a SpecScore from the four raw dimensions.

    Each input is clamped to [0, 100]. Evidence strings are stored so
    a reviewer can replay why a score was given without re-running.
    """
    ev = evidence or {}

    def _clamp(v: float) -> float:
        return max(0.0, min(100.0, float(v)))

    dims = (
        DimensionScore("scaffold_completeness", _clamp(scaffold_completeness), ev.get("scaffold_completeness", "")),
        DimensionScore("test_suite_pass", _clamp(test_suite_pass), ev.get("test_suite_pass", "")),
        DimensionScore("primitive_gate_pass", _clamp(primitive_gate_pass), ev.get("primitive_gate_pass", "")),
        DimensionScore("hand_editability", _clamp(hand_editability), ev.get("hand_editability", "")),
    )
    return SpecScore(spec_id=spec_id, tier=tier, dimensions=dims)


@dataclass(frozen=True)
class BenchmarkReport:
    kit_version: str
    maestro_model: str
    generated_at: str       # ISO-8601 UTC
    scores: tuple[SpecScore, ...]

    @property
    def overall(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.total for s in self.scores) / len(self.scores)

    def by_tier(self) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for s in self.scores:
            buckets.setdefault(s.tier, []).append(s.total)
        return {tier: sum(v) / len(v) for tier, v in buckets.items() if v}

    def as_dict(self) -> dict:
        return {
            "kit_version": self.kit_version,
            "maestro_model": self.maestro_model,
            "generated_at": self.generated_at,
            "overall": round(self.overall, 2),
            "by_tier": {k: round(v, 2) for k, v in self.by_tier().items()},
            "scores": [s.as_dict() for s in self.scores],
        }

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=False), encoding="utf-8")


def aggregate(scores: Iterable[SpecScore], *, kit_version: str, maestro_model: str, generated_at: str) -> BenchmarkReport:
    return BenchmarkReport(
        kit_version=kit_version,
        maestro_model=maestro_model,
        generated_at=generated_at,
        scores=tuple(scores),
    )
