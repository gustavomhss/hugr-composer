"""Aggregate subagent artifacts → benchmarks/latest_score.json.

Reads plan.json + scaffold_plan.md from each spec's workdir under the
chosen run (default `benchmarks/_runs/v0/`), scores each via
`SubagentMaestro`, aggregates, and writes the canonical
`benchmarks/latest_score.json` that satisfies CONTRACT §B3.5.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.bench.rubric import aggregate, score_spec
from engine.bench.runner import SPECS_ROOT, _discover_specs, _kit_version
from engine.bench.subagent_maestro import SubagentMaestro

SKILL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = SKILL_ROOT / "benchmarks" / "_runs" / "v0"
DEFAULT_OUT = SKILL_ROOT / "benchmarks" / "latest_score.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model-label", default="cli-subagent-sonnet-4-6")
    parser.add_argument("--methodology", default="plan_level_v0")
    args = parser.parse_args(argv)

    if not args.run.exists():
        print(f"FAIL: run dir missing: {args.run}", file=sys.stderr)
        return 1

    adapter = SubagentMaestro(runs_dir=args.run, model_label=args.model_label)

    scores = []
    missing: list[str] = []
    for spec_path in _discover_specs():
        tier = spec_path.parent.name
        workdir = args.run / tier / spec_path.stem
        if not (workdir / "plan.json").exists():
            missing.append(f"{tier}/{spec_path.stem}")
        result = adapter.run_spec(spec_path, workdir)
        s = score_spec(
            result.spec_id, result.tier,
            scaffold_completeness=result.scaffold_completeness,
            test_suite_pass=result.test_suite_pass,
            primitive_gate_pass=result.primitive_gate_pass,
            hand_editability=result.hand_editability,
            evidence=result.evidence,
        )
        scores.append(s)

    report = aggregate(
        scores,
        kit_version=_kit_version(),
        maestro_model=adapter.model_name(),
        generated_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    )
    data = report.as_dict()
    data["methodology"] = args.methodology
    data["methodology_notes"] = (
        "Plan-level v0: subagent Maestro produces a requirement→primitive/tool map "
        "(plan.json + scaffold_plan.md) using the kit's discovery MCP tools. "
        "Scores reflect discoverability + composition accuracy, not executed code. "
        "Full-codebase benchmark is tracked for Phase 5+ per ROADMAP.md."
    )
    if missing:
        data["missing_artifacts"] = missing

    import json
    args.out.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")

    print(f"overall: {report.overall:.2f}")
    for tier, v in report.by_tier().items():
        print(f"  {tier:12} {v:6.2f}")
    for s in scores:
        print(f"  {s.spec_id:55} {s.total:6.2f}")
    if missing:
        print(f"missing artifacts: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
