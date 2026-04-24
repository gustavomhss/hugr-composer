"""Snapshot benchmarks/latest_score.json + code_level_score.json into evidence.

PRODUCT §4 target: "≥70% single-shot success on unseen specs" — benchmark
results live in `skills/.../benchmarks/` by convention, but LAUNCH.md §1.3
requires every PRODUCT claim to be mapped to an artefact IN `/evidence/`.

This probe does NOT re-run the benchmark (that's a 30-60min job owned by
benchmark-nightly.yml CI). It snapshots the existing canonical score files
into `/evidence/deterministic/benchmark_scores.json` with:

- Plan-level per-spec breakdown (from `benchmarks/latest_score.json`).
- Code-level per-spec breakdown (from `benchmarks/code_level_score.json`).
- Aggregate targets (floor from `baseline_floor.json`).
- Provenance (source file + mtime + generated_at).

The consumer can audit per-spec rows without leaving `/evidence/`.

Output:
    evidence/deterministic/benchmark_scores.json
    {
      "_meta": {...},
      "plan_level": {...from latest_score.json...},
      "code_level": {...from code_level_score.json...},
      "floors": {...from baseline_floor.json...},
      "per_spec": [ {spec_id, tier, plan_score, code_score, covered} ],
      "summary": {plan_overall, code_overall, floor_plan, floor_code, passed}
    }

Exit 0 iff plan_overall ≥ floor_plan AND code_overall ≥ floor_code.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BENCH_DIR = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / "benchmarks"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _read_json(p: pathlib.Path) -> dict:
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def main() -> int:
    plan = _read_json(BENCH_DIR / "latest_score.json")
    code = _read_json(BENCH_DIR / "code_level_score.json")
    floor = _read_json(BENCH_DIR / "baseline_floor.json")

    plan_scores = {s["spec_id"]: s for s in plan.get("scores", [])}
    # code_level uses "spec_results" with "score" (not "scores" / "total")
    code_scores = {s["spec_id"]: s for s in code.get("spec_results", [])}

    all_specs = sorted(set(plan_scores.keys()) | set(code_scores.keys()))
    per_spec = []
    for sid in all_specs:
        p = plan_scores.get(sid, {})
        c = code_scores.get(sid, {})
        per_spec.append({
            "spec_id": sid,
            "tier": p.get("tier") or c.get("tier"),
            "plan_score": p.get("total"),
            "code_score": c.get("score"),
            "code_tests_passed": c.get("tests_passed"),
            "code_tests_total": c.get("tests_total"),
            "covered_by_plan": bool(p),
            "covered_by_code": bool(c) and c.get("covered", True),
        })

    plan_overall = plan.get("overall")
    # code_level uses a different key convention
    code_overall = code.get("overall") or code.get("code_level_score")
    plan_floor = floor.get("plan_level_floor") or floor.get("floor") or 90.0
    code_floor = floor.get("code_level_floor") or 70.0

    passed = (
        plan_overall is not None
        and code_overall is not None
        and plan_overall >= plan_floor
        and code_overall >= code_floor
    )

    out = {
        "_meta": {
            "command": ".venv/bin/python evidence/_harness/benchmark_scores_snapshot.py",
            "cwd": "repo root",
            "commit": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grading": "exit 0 iff plan_overall ≥ plan_floor AND code_overall ≥ code_floor",
            "source_files": {
                "plan": "skills/SKILL-001-fastapi-production/benchmarks/latest_score.json",
                "code": "skills/SKILL-001-fastapi-production/benchmarks/code_level_score.json",
                "floor": "skills/SKILL-001-fastapi-production/benchmarks/baseline_floor.json",
            },
        },
        "plan_level": {
            "kit_version": plan.get("kit_version"),
            "maestro_model": plan.get("maestro_model"),
            "generated_at": plan.get("generated_at"),
            "overall": plan_overall,
            "by_tier": plan.get("by_tier", {}),
            "specs_count": len(plan.get("scores", [])),
        },
        "code_level": {
            "kit_version": code.get("kit_version"),
            "maestro_model": code.get("maestro_model"),
            "generated_at": code.get("generated_at"),
            "overall": code_overall,
            "coverage": code.get("coverage"),
            "covered_specs": code.get("covered_specs"),
            "by_tier": code.get("by_tier", {}),
        },
        "floors": {
            "plan_level": plan_floor,
            "code_level": code_floor,
        },
        "summary": {
            "plan_overall": plan_overall,
            "code_overall": code_overall,
            "plan_headroom": (plan_overall - plan_floor) if plan_overall is not None else None,
            "code_headroom": (code_overall - code_floor) if code_overall is not None else None,
            "per_spec_count": len(per_spec),
            "passed": passed,
        },
        "per_spec": per_spec,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
