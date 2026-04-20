"""Code-level benchmark harness (B3.6).

Runs pytest against the executable targets declared in
`benchmarks/spec_code_level_map.json` and aggregates a code-level
score alongside the plan-level score from the Phase-3 harness.

Key design decision — coverage vs score separation
  A spec is EITHER covered (has a local executable target) OR pending
  (no example yet). We report TWO numbers, never conflated:

    code_level_score       Mean score across COVERED specs only.
                           Pure signal about whether the covered
                           targets actually behave correctly. Score
                           100 means every covered test passed.

    coverage               (#covered / #total) × 100. Tells a reader
                           how many of the 20 specs have a code-level
                           verification surface at all.

  The overall v0.1.0 story reads honestly as:
    "plan-level 100% · code-level 100% across 5/20 covered specs
     (25% coverage) — the remaining 15 specs are pending and
     explicitly not scored."

  Conflating would hide the gap. The plan-level score is the BFS
  ceiling estimate; the code-level score is a DFS sample of truth.

Usage:
    PYTHONPATH=. python -m engine.bench.code_level           # runs + prints
    PYTHONPATH=. python -m engine.bench.code_level --publish  # writes json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SKILL_ROOT.parents[1]
MAP_PATH = SKILL_ROOT / "benchmarks" / "spec_code_level_map.json"
OUT_PATH = SKILL_ROOT / "benchmarks" / "code_level_score.json"


@dataclass(frozen=True)
class SpecResult:
    spec_id: str
    tier: str
    covered: bool
    score: float | None        # None when pending
    tests_passed: int = 0
    tests_total: int = 0
    notes: str = ""
    pending_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = {
            "spec_id": self.spec_id,
            "tier": self.tier,
            "covered": self.covered,
            "score": self.score,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "notes": self.notes,
        }
        if self.pending_reason:
            d["pending_reason"] = self.pending_reason
        return d


def _kit_version() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, cwd=REPO_ROOT,
        )
        return (out.stdout or "unknown").strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _parse_pytest_summary(stdout: str) -> tuple[int, int]:
    """Return (passed, total) parsed from the final pytest summary line.

    pytest's summary line looks like:
        `4 passed, 1 skipped in 0.30s`
    or on failures:
        `2 failed, 3 passed in 0.42s`
    """
    import re
    last = ""
    for line in stdout.splitlines():
        if re.search(r"\b\d+\s+(passed|failed|error|skipped)\b", line):
            last = line
    if not last:
        return (0, 0)
    passed = sum(int(m.group(1)) for m in re.finditer(r"(\d+)\s+passed", last))
    failed = sum(int(m.group(1)) for m in re.finditer(r"(\d+)\s+failed", last))
    errors = sum(int(m.group(1)) for m in re.finditer(r"(\d+)\s+error", last))
    skipped = sum(int(m.group(1)) for m in re.finditer(r"(\d+)\s+skipped", last))
    total = passed + failed + errors + skipped
    return (passed, total)


def _score_one(spec_id: str, target_rel: str, python_bin: Path) -> SpecResult:
    """Run pytest against ``target_rel`` (relative to REPO_ROOT)."""
    tier = spec_id.split("/", 1)[0]
    target = REPO_ROOT / target_rel
    if not target.exists():
        return SpecResult(
            spec_id=spec_id, tier=tier, covered=False, score=None,
            pending_reason=f"target {target_rel} missing on disk",
        )
    out = subprocess.run(
        [str(python_bin), "-m", "pytest", "-q", "--tb=no", str(target)],
        capture_output=True, text=True, check=False, cwd=REPO_ROOT,
    )
    passed, total = _parse_pytest_summary(out.stdout + "\n" + out.stderr)
    if total == 0:
        return SpecResult(
            spec_id=spec_id, tier=tier, covered=True, score=0.0,
            tests_passed=0, tests_total=0,
            notes=f"pytest collected no tests under {target_rel}",
        )
    score = 100.0 * passed / total if total else 0.0
    return SpecResult(
        spec_id=spec_id, tier=tier, covered=True, score=round(score, 2),
        tests_passed=passed, tests_total=total,
        notes=f"pytest: {passed}/{total} passed",
    )


def _load_map() -> dict[str, dict[str, Any]]:
    return json.loads(MAP_PATH.read_text())["entries"]


def run() -> dict[str, Any]:
    entries = _load_map()
    python_bin = Path(sys.executable)
    results: list[SpecResult] = []
    for spec_id, cfg in entries.items():
        tier = spec_id.split("/", 1)[0]
        target = cfg.get("code_level_target")
        if not target:
            results.append(SpecResult(
                spec_id=spec_id, tier=tier, covered=False, score=None,
                pending_reason=cfg.get("pending_reason", "not covered"),
            ))
            continue
        results.append(_score_one(spec_id, target, python_bin))

    covered = [r for r in results if r.covered and r.score is not None]
    total_specs = len(results)
    coverage_pct = 100.0 * len(covered) / total_specs if total_specs else 0.0
    code_level_score = (
        sum(r.score for r in covered) / len(covered) if covered else 0.0
    )

    by_tier: dict[str, dict[str, Any]] = {}
    for tier in ("baseline", "mid", "adversarial"):
        tier_results = [r for r in results if r.tier == tier]
        tier_covered = [r for r in tier_results if r.covered and r.score is not None]
        by_tier[tier] = {
            "covered": len(tier_covered),
            "total": len(tier_results),
            "score": (
                round(sum(r.score for r in tier_covered) / len(tier_covered), 2)
                if tier_covered else None
            ),
        }

    return {
        "methodology": "code_level_pytest_direct",
        "methodology_notes": (
            "Runs pytest against the executable target declared for each "
            "spec in benchmarks/spec_code_level_map.json. code_level_score "
            "is the mean per-spec score across COVERED specs only; "
            "coverage reports the #covered / #total ratio. Pending specs "
            "are explicitly NOT scored (score=null) — conflating would hide "
            "the remaining work."
        ),
        "code_level_score": round(code_level_score, 2),
        "coverage": round(coverage_pct, 2),
        "covered_specs": len(covered),
        "total_specs": total_specs,
        "by_tier": by_tier,
        "spec_results": [r.as_dict() for r in results],
        "kit_version": _kit_version(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true",
                        help="write benchmarks/code_level_score.json")
    args = parser.parse_args(argv)

    report = run()
    print(
        f"code_level_score={report['code_level_score']:.2f}  "
        f"coverage={report['coverage']:.2f}%  "
        f"({report['covered_specs']}/{report['total_specs']} specs)"
    )
    for tier, v in report["by_tier"].items():
        score = v["score"]
        score_str = f"{score:.2f}" if score is not None else "  —  "
        print(f"  {tier:12} covered={v['covered']}/{v['total']:<2}  score={score_str}")

    if args.publish:
        OUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=False))
        print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
