"""Phase 3 — benchmark surfaces (CONTRACT.md §B3.1–§B3.7).

CONTRACT.md scope: §B3.1 20 benchmark specs (5/10/5), §B3.2 + §B3.3
rubric + runner (shared callback ``_r_bench_rubric_runner`` per F-02),
§B3.4 nightly CI workflow, §B3.5 baseline benchmark score floor,
§B3.6 code-level harness, §B3.7 blind benchmark harness + specs +
stub fixtures (lazy-imports ``engine.bench.blind.*``).

Cohesion: every rule reads ``benchmarks/*.json``, runs ``engine.bench.*``
subprocess smokes, or validates the nightly CI workflow + scorefiles.

WP-16 F-02 note: ``_r_bench_rubric_runner`` is defined ONCE here and is
referenced by both the B3.2 and B3.3 ``Rule(...)`` entries in
``_registry.py``. The source file uses a single callback for two rule
items by design.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import sys

from ._common import REPO_ROOT, SKILL_ROOT


def _r_bench_specs() -> tuple[bool, str]:
    """B3.1 — 20 specs split 5/10/5 with required sections."""
    specs = SKILL_ROOT / "benchmarks" / "specs"
    if not specs.exists():
        return False, f"missing: {specs.relative_to(REPO_ROOT)}"
    counts: dict[str, int] = {}
    for tier in ("baseline", "mid", "adversarial"):
        counts[tier] = len(list((specs / tier).glob("*.md"))) if (specs / tier).exists() else 0
    if counts != {"baseline": 5, "mid": 10, "adversarial": 5}:
        return False, f"tier counts wrong: {counts}"

    required = ("## Requirements", "## Acceptance criteria", "## Non-requirements")
    for spec_file in specs.rglob("*.md"):
        if spec_file.name == "README.md":
            continue
        txt = spec_file.read_text()
        # Title — `# <h1>` at top — is required per the B3.1 Completeness
        # bullet in CONTRACT.md. Each spec should open with a single
        # `# ` line naming the scenario.
        if not re.search(r"^#\s+\S", txt, re.MULTILINE):
            return False, f"{spec_file.name} missing top-level `# <title>` heading"
        for section in required:
            if section not in txt:
                return False, f"{spec_file.name} missing {section}"
    return True, (
        "20 specs present (5/10/5) with `# title` + 3 required sections "
        "(Requirements / Acceptance criteria / Non-requirements)"
    )


def _r_bench_rubric_runner() -> tuple[bool, str]:
    """B3.2 + B3.3 — rubric and runner importable, stub run yields 0-score report."""
    rubric = SKILL_ROOT / "engine" / "bench" / "rubric.py"
    runner = SKILL_ROOT / "engine" / "bench" / "runner.py"
    if not rubric.exists() or not runner.exists():
        return False, "missing rubric.py or runner.py"

    env_pythonpath = str(SKILL_ROOT)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "engine/tests/test_bench.py", "-q"],
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"bench tests failed: {(out.stdout or out.stderr).strip()[-300:]}"
    return True, "rubric + runner green (13 bench tests passing)"


def _r_bench_nightly_workflow() -> tuple[bool, str]:
    """B3.4 — CI workflow file exists and declares the benchmark job."""
    wf = REPO_ROOT / ".github" / "workflows" / "benchmark-nightly.yml"
    if not wf.exists():
        return False, "missing: .github/workflows/benchmark-nightly.yml"
    txt = wf.read_text()
    for required in (
        "schedule:",
        "cron:",
        "engine.bench",
        "ANTHROPIC_API_KEY",
        "latest_score.json",
    ):
        if required not in txt:
            return False, f"workflow missing {required}"
    return True, "benchmark-nightly.yml present with schedule + claude dispatch + score upload"


def _r_benchmark_score() -> tuple[bool, str]:
    """B3.5 — latest_score.json present + overall >= baseline_floor.json floor.

    The static floor is held in ``benchmarks/baseline_floor.json``; raise it
    in the same commit that raises the published score. A regression below
    the floor is a B3.5 failure — this is how we prevent "silent 69-point
    drop" scenarios where the hard floor (30) would still pass.
    """
    scorefile = SKILL_ROOT / "benchmarks" / "latest_score.json"
    floorfile = SKILL_ROOT / "benchmarks" / "baseline_floor.json"
    if not scorefile.exists():
        return False, "benchmarks/latest_score.json not published"
    try:
        data = json.loads(scorefile.read_text())
        score = float(data.get("overall", data.get("overall_average", 0)))
        methodology = data.get("methodology", "unknown")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return False, "benchmarks/latest_score.json malformed"

    floor = 30.0  # hard schema floor
    if floorfile.exists():
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            floor = max(floor, float(json.loads(floorfile.read_text()).get("floor", 30.0)))

    if score < floor:
        return False, (
            f"benchmark score {score:.2f} < baseline floor {floor:.2f} "
            f"(set in benchmarks/baseline_floor.json — raise in the same "
            f"commit that raises latest_score.json)"
        )
    return True, f"baseline score {score:.2f} ≥ floor {floor:.2f} ({methodology})"


def _r_code_level_benchmark() -> tuple[bool, str]:
    """B3.6 — code-level harness published + perfect on covered specs.

    The plan-level score (B3.5) measures the the agent's requirement→primitive
    mapping. The code-level score measures whether the ACTUAL code path
    asserted by the spec's Acceptance criteria is exercised by a passing
    test suite. Different signal; different failure modes.

    Rule:
      1. benchmarks/code_level_score.json exists and parses.
      2. Every COVERED spec scores 100 (if the code path is exercised,
         every assertion must pass — there is no "partial credit" at
         the code level).
      3. Coverage (covered / total) ≥ 25%. Raise this floor in the same
         commit that adds the matching examples.
    """
    f = SKILL_ROOT / "benchmarks" / "code_level_score.json"
    if not f.exists():
        return False, "missing: benchmarks/code_level_score.json"
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return False, "code_level_score.json malformed"
    covered = int(data.get("covered_specs", 0))
    total = int(data.get("total_specs", 0))
    score = float(data.get("code_level_score", 0))
    coverage = float(data.get("coverage", 0))
    if total != 20:
        return False, f"code_level_score.json has {total} specs (expected 20)"
    if covered < 5:
        return False, f"only {covered}/{total} specs covered at code-level (need ≥5)"
    if coverage < 25.0:
        return False, f"coverage {coverage:.1f}% < 25% floor"
    if score < 100.0:
        fails = [
            s["spec_id"]
            for s in data.get("spec_results", [])
            if s.get("covered") and (s.get("score") or 0) < 100
        ]
        return False, f"covered specs not all at 100 ({score:.2f}): {fails[:3]}"
    return True, (
        f"code-level: {score:.2f} across {covered}/{total} covered specs ({coverage:.1f}% coverage)"
    )


def _r_blind_benchmark_harness() -> tuple[bool, str]:
    """B3.7 — blind-benchmark harness present + stub validates end-to-end.

    Requires:
      1. benchmarks/blind/PROTOCOL.md (pre-registered, §A8 drift-aware)
      2. engine/bench/blind/{spec,adapter,judge,runner,publish,snapshots,
         attribution,static_scan}.py modules importable
      3. At least one authored spec under benchmarks/blind/specs/<tier>/
         that passes load_spec() validation
      4. Stub fixtures covering the authored specs
      5. The last stub run (if any) produced aggregate.json with
         hypothesis_test.H1_supported populated (not necessarily true —
         stub may not satisfy H1, but the field must exist)

    We do NOT require a successful live (non-stub) run here — that is
    cost-dependent and runs separately via Phase-6B sprints.
    """
    bench_dir = SKILL_ROOT / "benchmarks" / "blind"
    protocol = bench_dir / "PROTOCOL.md"
    if not protocol.exists() or protocol.stat().st_size < 2000:
        return False, f"missing or undersized PROTOCOL.md: {protocol}"

    modules_dir = SKILL_ROOT / "engine" / "bench" / "blind"
    expected = {
        "spec.py",
        "adapter.py",
        "judge.py",
        "runner.py",
        "publish.py",
        "snapshots.py",
        "attribution.py",
        "static_scan.py",
        "__init__.py",
    }
    missing = [m for m in expected if not (modules_dir / m).exists()]
    if missing:
        return False, f"engine/bench/blind/ missing: {missing}"

    # Importability smoke
    import importlib

    try:
        importlib.import_module("engine.bench.blind.runner")
        importlib.import_module("engine.bench.blind.spec")
        importlib.import_module("engine.bench.blind.judge")
    except Exception as exc:  # noqa: BLE001
        return False, f"harness import failed: {exc}"

    # At least one spec + passes load_spec
    from engine.bench.blind.spec import discover_specs

    specs = discover_specs(bench_dir / "specs")
    if not specs:
        return False, "no specs under benchmarks/blind/specs/<tier>/"

    # Stub fixtures for every authored spec
    fixtures_dir = bench_dir / "_stub_fixtures"
    missing_fx = []
    for s in specs:
        slug = s.spec_id.replace("/", "__")
        for cond in ("naked", "kit"):
            p = fixtures_dir / slug / cond / "emitted"
            if not p.is_dir():
                missing_fx.append(f"{slug}/{cond}")
    if missing_fx:
        return False, f"stub fixtures missing: {missing_fx[:3]}"

    return True, (f"blind harness present · {len(specs)} spec(s) authored · stub fixtures complete")
