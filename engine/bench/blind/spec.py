"""Spec loader + validator.

A "spec" is a directory under `benchmarks/blind/specs/<tier>/<id>/` that
carries the agent-visible brief, the sealed judge, and metadata. This
module validates the shape and hashes the brief for contamination guards.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TIER_PREDICTIONS = {
    "calibration": {"naked_min": 75, "naked_max": 95, "kit_min": 80, "kit_max": 95},
    "hard":        {"naked_min": 10, "naked_max": 40, "kit_min": 55, "kit_max": 85},
    "impossible":  {"naked_min":  0, "naked_max": 15, "kit_min": 30, "kit_max": 60},
}

DIFFICULTY_AXES = frozenset({
    "concurrency", "exactly_once", "causal_order", "multi_invariant",
    "failure_injection", "property_based", "large_n_scaling", "type_safety",
    "security", "observability",
})


@dataclass(frozen=True)
class Spec:
    spec_id: str                    # e.g. "hard/01_financial_ledger"
    tier: str                       # "calibration" | "hard" | "impossible"
    root: Path                      # directory containing brief.md, judge/, ...
    brief: str                      # agent-visible text
    brief_sha256: str
    metadata: dict[str, Any]
    boot_command: str               # e.g. "uvicorn app.main:app --port {PORT}"
    judge_dir: Path                 # contains sealed test files
    health_probe: str               # e.g. "/health"
    timeout_s: int                  # pytest timeout
    boot_health_timeout_s: int = 45 # max wait for health probe 200

    @property
    def difficulty_axes(self) -> list[str]:
        return list(self.metadata.get("difficulty_axes", []))

    @property
    def required_primitives(self) -> list[str]:
        return list(self.metadata.get("required_primitives", []))

    @property
    def predicted_naked_score(self) -> float:
        return float(self.metadata.get("predicted_naked_score", 0.0))

    @property
    def predicted_kit_score(self) -> float:
        return float(self.metadata.get("predicted_kit_score", 0.0))


class SpecValidationError(ValueError):
    pass


def load_spec(spec_dir: Path) -> Spec:
    """Load + validate a spec directory. Raises SpecValidationError."""
    brief_path = spec_dir / "brief.md"
    meta_path = spec_dir / "metadata.json"
    judge_dir = spec_dir / "judge"

    for required, name in ((brief_path, "brief.md"), (meta_path, "metadata.json")):
        if not required.exists():
            raise SpecValidationError(f"{spec_dir.name}: missing {name}")
    if not judge_dir.is_dir():
        raise SpecValidationError(f"{spec_dir.name}: missing judge/ directory")

    brief = brief_path.read_text(encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    tier = meta.get("tier")
    if tier not in TIER_PREDICTIONS:
        raise SpecValidationError(f"tier must be one of {sorted(TIER_PREDICTIONS)}; got {tier!r}")

    axes = meta.get("difficulty_axes") or []
    bad = [a for a in axes if a not in DIFFICULTY_AXES]
    if bad:
        raise SpecValidationError(f"unknown difficulty_axes: {bad}")

    predictions = TIER_PREDICTIONS[tier]
    pn = float(meta.get("predicted_naked_score", -1))
    pk = float(meta.get("predicted_kit_score", -1))
    if not (0 <= pn <= 100) or not (0 <= pk <= 100):
        raise SpecValidationError("predicted scores must be in [0,100]")
    if not (predictions["naked_min"] <= pn <= predictions["naked_max"]):
        raise SpecValidationError(
            f"predicted_naked_score {pn} out of tier band {predictions['naked_min']}-{predictions['naked_max']}"
        )

    required_keys = {"tier", "difficulty_axes", "required_primitives",
                     "predicted_naked_score", "predicted_kit_score",
                     "boot_command", "health_probe", "timeout_s",
                     "authored_at", "author"}
    missing = required_keys - meta.keys()
    if missing:
        raise SpecValidationError(f"metadata.json missing keys: {sorted(missing)}")

    # judge/ must contain at least one test_*.py
    if not any(judge_dir.glob("test_*.py")):
        raise SpecValidationError(f"{spec_dir.name}: judge/ has no test_*.py")

    # Compute brief hash (contamination guard — recorded in every trajectory)
    h = hashlib.sha256(brief.encode("utf-8")).hexdigest()

    spec_id = f"{tier}/{spec_dir.name}"
    return Spec(
        spec_id=spec_id,
        tier=tier,
        root=spec_dir,
        brief=brief,
        brief_sha256=h,
        metadata=meta,
        boot_command=meta["boot_command"],
        judge_dir=judge_dir,
        health_probe=meta["health_probe"],
        timeout_s=int(meta["timeout_s"]),
        boot_health_timeout_s=int(meta.get("boot_health_timeout_s", 45)),
    )


def discover_specs(specs_root: Path) -> list[Spec]:
    """Find every spec directory under specs_root/<tier>/<id>/."""
    out: list[Spec] = []
    for tier in sorted(TIER_PREDICTIONS):
        tier_dir = specs_root / tier
        if not tier_dir.is_dir():
            continue
        for d in sorted(tier_dir.iterdir()):
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            out.append(load_spec(d))
    return out
