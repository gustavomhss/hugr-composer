"""Counterfactual deltas: WITH-HuGR (single_shot) vs WITHOUT-HuGR (counterfactual).

Reads:
    evidence/external-eval/single_shot_benchmark/results.json
    evidence/external-eval/counterfactual/results.json

Writes:
    evidence/external-eval/counterfactual/deltas.json
    {
      "per_spec": [
        {"spec": ..., "with_hugr": {...}, "without_hugr": {...},
         "tokens_delta_pct": ..., "wallclock_delta_pct": ...,
         "loc_delta_pct": ..., "grade_delta": ...}
      ],
      "summary": {
        "median_tokens_delta_pct": ...,
        "median_wallclock_delta_pct": ...,
        "median_loc_delta_pct": ...,
        "grade_delta_count": {hugr_better: N, baseline_better: M, tie: K}
      }
    }

Honest framing:
    - This is a SAME-MODEL relative comparison.
    - It does NOT prove "cheaper than a real human engineer."
    - Population-scale telemetry from Phase B+ closes that absolute claim.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys


def _safe_pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round((b - a) / b * 100, 2)


def main(single_shot_path: pathlib.Path, counterfactual_path: pathlib.Path) -> int:
    if not single_shot_path.exists() or not counterfactual_path.exists():
        print(json.dumps({"_status": "results files empty at Wave I-1; run external-eval first"}, indent=2))
        return 0

    ss = json.load(single_shot_path.open())
    cf = json.load(counterfactual_path.open())

    ss_by_spec = {r["spec"]: r for r in ss.get("results", [])}
    cf_by_spec = {r["spec"]: r for r in cf.get("results", [])}

    per_spec: list[dict] = []
    grade_count = {"hugr_better": 0, "baseline_better": 0, "tie": 0}
    tokens_deltas, wall_deltas, loc_deltas = [], [], []

    for spec in sorted(set(ss_by_spec) | set(cf_by_spec)):
        s = ss_by_spec.get(spec, {})
        c = cf_by_spec.get(spec, {})
        if s.get("passed") and not c.get("passed"):
            grade_count["hugr_better"] += 1
        elif c.get("passed") and not s.get("passed"):
            grade_count["baseline_better"] += 1
        else:
            grade_count["tie"] += 1

        tk = _safe_pct(s.get("total_tokens"), c.get("total_tokens"))
        wl = _safe_pct(s.get("wallclock_s"), c.get("wallclock_s"))
        lc = _safe_pct(s.get("emitted_loc"), c.get("emitted_loc"))
        if tk is not None: tokens_deltas.append(tk)
        if wl is not None: wall_deltas.append(wl)
        if lc is not None: loc_deltas.append(lc)
        per_spec.append({
            "spec": spec,
            "with_hugr": s,
            "without_hugr": c,
            "tokens_delta_pct": tk,
            "wallclock_delta_pct": wl,
            "loc_delta_pct": lc,
        })

    summary = {
        "median_tokens_delta_pct": round(statistics.median(tokens_deltas), 2) if tokens_deltas else None,
        "median_wallclock_delta_pct": round(statistics.median(wall_deltas), 2) if wall_deltas else None,
        "median_loc_delta_pct": round(statistics.median(loc_deltas), 2) if loc_deltas else None,
        "grade_delta_count": grade_count,
        "interpretation": "positive % = HuGR-assisted is cheaper / faster / smaller; negative = baseline is.",
    }
    print(json.dumps({"summary": summary, "per_spec": per_spec}, indent=2))
    return 0


if __name__ == "__main__":
    here = pathlib.Path(__file__).resolve()
    ss = here.parents[3] / "single_shot_benchmark" / "results.json"
    cf = here.parents[2] / "results.json"
    sys.exit(main(ss, cf))
