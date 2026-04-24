"""Compute cross-model variance from cross_model_fnf/results.json.

Emits variance_report.json with:
  - per-spec score spread (max - min across models)
  - per-model overall pass rate
  - CV% = stddev(model_overall) / mean(model_overall) × 100

Target: CV ≤ 10% → kit carries weight (model-agnostic).
         CV > 10% → "model-agnostic" claim is weaker than asserted.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys


def compute(results_path: pathlib.Path) -> dict:
    data = json.loads(results_path.read_text())
    runs = data.get("results", [])
    by_model: dict[str, list[bool]] = {}
    by_spec: dict[str, dict[str, bool]] = {}
    for r in runs:
        m = r["model"]
        s = r["spec"]
        passed = bool(r["passed"])
        by_model.setdefault(m, []).append(passed)
        by_spec.setdefault(s, {})[m] = passed

    per_model = {
        m: {
            "runs": len(v),
            "passed": sum(v),
            "pass_rate": round(sum(v) / len(v), 3) if v else 0.0,
        }
        for m, v in by_model.items()
    }

    per_spec = []
    for spec, vals in sorted(by_spec.items()):
        scores = [1.0 if ok else 0.0 for ok in vals.values()]
        per_spec.append({
            "spec": spec,
            "by_model": {m: bool(ok) for m, ok in vals.items()},
            "score_spread": max(scores) - min(scores) if scores else 0.0,
        })

    overall = [m["pass_rate"] for m in per_model.values()]
    mean = statistics.fmean(overall) if overall else 0.0
    stdev = statistics.pstdev(overall) if len(overall) > 1 else 0.0
    cv_pct = (stdev / mean * 100) if mean else 0.0

    verdict = "model-agnostic" if cv_pct <= 10.0 else "model-dependent"
    return {
        "per_model": per_model,
        "per_spec": per_spec,
        "overall_mean_pass_rate": round(mean, 3),
        "overall_stdev": round(stdev, 3),
        "cv_pct": round(cv_pct, 2),
        "target": "cv_pct <= 10",
        "verdict": verdict,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # default path relative to script
        results = pathlib.Path(__file__).parent.parent / "results.json"
    else:
        results = pathlib.Path(sys.argv[1])
    if not results.exists() or results.stat().st_size <= 20:
        print(json.dumps({"_status": "results.json empty at Wave H — run run.py first"}, indent=2))
        sys.exit(0)
    print(json.dumps(compute(results), indent=2))
