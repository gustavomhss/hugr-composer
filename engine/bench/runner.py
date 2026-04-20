"""Benchmark runner — CONTRACT §B3.3.

Harness that drives a Maestro implementation against every spec in
`benchmarks/specs/` and records transcripts + scores.

The runner does NOT couple to Anthropic or any specific LLM SDK; the
Maestro is any callable that implements `MaestroAdapter`. This keeps the
harness unit-testable with a deterministic stub and production-capable
with a real Opus/Sonnet-backed Maestro.

Typical production entry point (invoked from the nightly workflow):

    runner = BenchmarkRunner(adapter=ClaudeMaestro())
    report = runner.run_all()
    report.write_json("benchmarks/latest_score.json")

Typical test entry point (deterministic, no LLM calls):

    runner = BenchmarkRunner(adapter=StubMaestro(scoreboard={"baseline/01_crud_todos": 80, ...}))
    report = runner.run_all()
    assert report.overall >= 30.0
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from engine.bench.rubric import BenchmarkReport, SpecScore, aggregate, score_spec

SKILL_ROOT = Path(__file__).resolve().parents[2]
SPECS_ROOT = SKILL_ROOT / "benchmarks" / "specs"
DEFAULT_REPORT = SKILL_ROOT / "benchmarks" / "latest_score.json"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    """Produced by a Maestro per spec. The runner converts this into a score."""
    spec_id: str
    tier: str
    scaffold_completeness: float
    test_suite_pass: float
    primitive_gate_pass: float
    hand_editability: float
    evidence: dict[str, str]
    transcript_path: Path | None = None


class MaestroAdapter(Protocol):
    """Implementors drive a real or stub Maestro against a spec."""

    def model_name(self) -> str: ...

    def run_spec(self, spec_path: Path, workdir: Path) -> RunResult:
        """Read the spec, invoke the Maestro, score the output.

        Implementations MUST return a fully-populated ``RunResult``.
        They SHOULD write the Maestro transcript into ``workdir`` and
        reference it in ``RunResult.transcript_path``.
        """
        ...


@dataclass
class StubMaestro:
    """Deterministic Maestro used by tests — never calls an LLM.

    ``scoreboard`` maps ``spec_id`` → one 0-100 number applied to every
    dimension. Anything not in the scoreboard scores zero (models a
    brand-new kit with no coverage).
    """
    scoreboard: dict[str, float]
    name: str = "stub"

    def model_name(self) -> str:
        return self.name

    def run_spec(self, spec_path: Path, workdir: Path) -> RunResult:
        tier = spec_path.parent.name
        spec_id = f"{tier}/{spec_path.stem}"
        value = float(self.scoreboard.get(spec_id, 0.0))
        return RunResult(
            spec_id=spec_id,
            tier=tier,
            scaffold_completeness=value,
            test_suite_pass=value,
            primitive_gate_pass=value,
            hand_editability=value,
            evidence={"stub": f"deterministic score {value}"},
            transcript_path=None,
        )


def _discover_specs(root: Path = SPECS_ROOT) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*.md")
        if p.name != "README.md" and p.parent != root
    )


@dataclass
class BenchmarkRunner:
    adapter: MaestroAdapter
    specs_root: Path = SPECS_ROOT
    workdir: Path | None = None           # temp dir per run by default
    on_spec_start: Callable[[Path], None] | None = None
    on_spec_end: Callable[[RunResult], None] | None = None

    def run_all(self, *, kit_version: str | None = None) -> BenchmarkReport:
        specs = _discover_specs(self.specs_root)
        if not specs:
            raise RuntimeError(f"no specs found under {self.specs_root}")

        results: list[SpecScore] = []
        workdir = self.workdir or (SKILL_ROOT / "benchmarks" / "_runs" / _timestamp())
        workdir.mkdir(parents=True, exist_ok=True)

        for spec_path in specs:
            if self.on_spec_start:
                self.on_spec_start(spec_path)
            spec_workdir = workdir / spec_path.parent.name / spec_path.stem
            spec_workdir.mkdir(parents=True, exist_ok=True)

            run = self.adapter.run_spec(spec_path, spec_workdir)
            score = score_spec(
                run.spec_id,
                run.tier,
                scaffold_completeness=run.scaffold_completeness,
                test_suite_pass=run.test_suite_pass,
                primitive_gate_pass=run.primitive_gate_pass,
                hand_editability=run.hand_editability,
                evidence=run.evidence,
            )
            results.append(score)

            if self.on_spec_end:
                self.on_spec_end(run)

        return aggregate(
            results,
            kit_version=kit_version or _kit_version(),
            maestro_model=self.adapter.model_name(),
            generated_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        )


def _timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _kit_version() -> str:
    """Best-effort git rev for reproducibility."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — requires an adapter choice.

    Default is `stub` (prints a canned zero-score report). To run against
    the real Claude-backed Maestro, use `--adapter claude`; the Claude
    adapter is intentionally not shipped in this module to keep the
    runner dependency-free. The caller wires it up at invocation time.
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="stub", choices=["stub"])
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    adapter: MaestroAdapter = StubMaestro(scoreboard={})
    runner = BenchmarkRunner(adapter=adapter)
    report = runner.run_all()
    report.write_json(args.out)
    print(json.dumps({"overall": round(report.overall, 2), "by_tier": report.by_tier()}, indent=2))
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
