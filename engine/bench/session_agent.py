"""Session agent — in-session benchmark adapter (CONTRACT B3.3).

Same artifact protocol as `engine/bench/subagent_runner.py`, but the
"agent" is the interactive session (an opencode/Claude agent) instead of
a spawned CLI subagent. No API key and no network are required: the
session reads each spec, uses `engine.discovery` to map every
requirement to real, non-hallucinated primitives, and writes
`plan.json` + `scaffold_plan.md` into the run workdir. `SubagentRunner`
then scores the artifacts mechanically, so the rubric is identical to the
CLI-subagent path.

Usage (inside the session):

    PYTHONPATH=. python -m engine.bench.session_agent --publish
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.bench.runner import SKILL_ROOT, _discover_specs, _timestamp
from engine.bench.subagent_runner import SubagentRunner, extract_acceptance, extract_requirements
from engine.discovery import find_primitive, suggest_composition

RUNS_ROOT = SKILL_ROOT / "benchmarks" / "_runs"
DEFAULT_REPORT = SKILL_ROOT / "benchmarks" / "latest_score.json"

_MIN_SCORE = 1.0  # discovery score threshold for a citation to count as a real match


@dataclass(frozen=True)
class _Mapping:
    primitives: list[str]
    rationale: str
    covered: bool


def _terms(req: str, limit: int = 12) -> str:
    """Project a requirement bullet onto discovery-friendly terms."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", req)
    stop = {
        "the",
        "and",
        "for",
        "that",
        "must",
        "not",
        "may",
        "with",
        "are",
        "any",
        "has",
        "its",
        "via",
        "per",
        "use",
        "using",
        "each",
        "all",
        "after",
        "only",
    }
    return " ".join(t for t in toks if t.lower() not in stop)[:220]


def _map_requirement(req: str) -> _Mapping:
    primitives: list[str] = []
    rationale = ""
    recipes = suggest_composition(intent=req, limit=3)
    for recipe in recipes:
        for p in recipe.get("primitives") or []:
            if p not in primitives:
                primitives.append(p)
        if not rationale and recipe.get("rationale"):
            rationale = recipe["rationale"]
    if not primitives:
        hits = find_primitive(query=_terms(req), limit=5)
        for h in hits:
            if h.get("score", 0) >= _MIN_SCORE:
                primitives.append(h["name"])
        if primitives:
            rationale = "mapped via find_primitive (top relevant primitive)"
    covered = bool(primitives)
    return _Mapping(primitives=primitives[:3], rationale=rationale, covered=covered)


def _make_plan(spec_path: Path, spec_id: str) -> dict[str, Any]:
    body = spec_path.read_text(encoding="utf-8")
    reqs = extract_requirements(body)
    crits = extract_acceptance(body)
    req_entries: list[dict[str, Any]] = []
    crit_entries: list[dict[str, Any]] = []
    for req in reqs:
        m = _map_requirement(req)
        req_entries.append(
            {
                "requirement": req,
                "primitives": m.primitives,
                "tools": [],
                "rationale": m.rationale or ("no primitive cited" if not m.covered else ""),
                "covered": m.covered,
            }
        )
    for crit in crits:
        m = _map_requirement(crit)
        crit_entries.append(
            {
                "criterion": crit,
                "addressed_by": m.primitives,
                "covered": m.covered,
            }
        )
    summary = (
        f"{spec_id}: {len(req_entries)} requirements, "
        f"{sum(1 for r in req_entries if r['covered'])} covered by "
        f"{sorted({p for r in req_entries for p in r['primitives']})[:6]}; "
        f"{sum(1 for c in crit_entries if c['covered'])}/{len(crit_entries)} acceptance "
        f"criteria addressed via discovery."
    )
    return {
        "spec_id": spec_id,
        "requirements": req_entries,
        "acceptance_criteria": crit_entries,
        "summary": summary,
    }


def _make_scaffold_plan(plan: dict[str, Any], spec_id: str) -> str:
    lines = [
        f"# Composition plan — {spec_id}",
        "",
        "## Overview",
        str(plan["summary"]),
        "",
        "## Primitive selections",
    ]
    for entry in plan["requirements"]:
        status = "covered" if entry["covered"] else "UNCOVERED"
        lines.append(f"- [{status}] {entry['requirement']}")
        if entry["primitives"]:
            lines.append(f"    primitives: {', '.join(entry['primitives'])}")
        if entry["rationale"]:
            lines.append(f"    rationale: {entry['rationale']}")
    lines += [
        "",
        "## Acceptance",
    ]
    for entry in plan["acceptance_criteria"]:
        status = "addressed" if entry["covered"] else "open"
        refs = ", ".join(entry["addressed_by"]) if entry["addressed_by"] else "(no primitive cited)"
        lines.append(f"- [{status}] {entry['criterion']} — {refs}")
    return "\n".join(lines)


def run() -> tuple[Path, SubagentRunner]:
    specs = _discover_specs()
    if not specs:
        raise RuntimeError("no specs found under benchmarks/specs")
    workdir = RUNS_ROOT / _timestamp()
    workdir.mkdir(parents=True, exist_ok=True)
    for spec_path in specs:
        tier = spec_path.parent.name
        spec_id = f"{tier}/{spec_path.stem}"
        spec_wd = workdir / tier / spec_path.stem
        spec_wd.mkdir(parents=True, exist_ok=True)
        plan = _make_plan(spec_path, spec_id)
        (spec_wd / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=False))
        (spec_wd / "scaffold_plan.md").write_text(_make_scaffold_plan(plan, spec_id))
    runner = SubagentRunner(runs_dir=workdir, model_label="session-agent-big-pickle")
    return workdir, runner


def main(argv: list[str] | None = None) -> int:
    import argparse

    from engine.bench.runner import BenchmarkRunner

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_REPORT, help="output latest_score.json path"
    )
    parser.add_argument(
        "--publish", action="store_true", help="write the report to --out (default: print only)"
    )
    args = parser.parse_args(argv)

    workdir, sub_runner = run()
    bench = BenchmarkRunner(adapter=sub_runner, workdir=workdir)
    report = bench.run_all()
    print(  # noqa: T201 - CLI report is the contract output for this adapter
        f"session-agent: overall={report.overall:.2f} "
        f"tiers={json.dumps({k: round(v, 2) for k, v in report.by_tier().items()})} "
        f"agent={report.maestro_model} kit={report.kit_version}"
    )
    if args.publish:
        report.write_json(args.out)
        print(f"wrote {args.out.relative_to(SKILL_ROOT)}")  # noqa: T201 - CLI status line
    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
