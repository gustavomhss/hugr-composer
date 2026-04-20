"""Orchestrator — spec × condition × seed → emit → judge → persist.

One `runner.main()` invocation produces a run directory under
`benchmarks/blind/results/<run_id>/` populated per PROTOCOL §5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from engine.bench.blind import HARNESS_VERSION
from engine.bench.blind.adapter import (
    ClaudeCliAdapter, ClaudeCliConfig, EmissionResult, MaestroAdapter,
    StubAdapter,
)
from engine.bench.blind.attribution import attribute
from engine.bench.blind.judge import JudgeResult, run_judge
from engine.bench.blind.snapshots import snapshot_workdir
from engine.bench.blind.spec import Spec, discover_specs
from engine.bench.blind.static_scan import run_static_scan

SKILL_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = SKILL_ROOT.parents[1]
SPECS_ROOT = SKILL_ROOT / "benchmarks" / "blind" / "specs"
RESULTS_ROOT = SKILL_ROOT / "benchmarks" / "blind" / "results"
MCP_CONFIG = REPO_ROOT / "examples" / "claude_code.mcp.json"

DEFAULT_SEEDS = [7919, 15485863, 2038074743]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, cwd=REPO_ROOT,
        )
        return (out.stdout or "unknown").strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _mcp_config_hash() -> str:
    if not MCP_CONFIG.exists():
        return "absent"
    return hashlib.sha256(MCP_CONFIG.read_bytes()).hexdigest()[:12]


def _attempt_dir(run_id: str, spec: Spec, condition: str, attempt: int) -> Path:
    safe = spec.spec_id.replace("/", "__")
    return RESULTS_ROOT / run_id / safe / condition / f"attempt_{attempt:02d}"


def _write_metrics(
    adir: Path, *, spec: Spec, condition: str, attempt: int, seed: int,
    emission: EmissionResult, judge: JudgeResult,
) -> dict:
    workdir = adir / "emitted"
    attribution_info = attribute(workdir, spec.required_primitives) if workdir.exists() else {
        "imported": [], "required": spec.required_primitives,
        "coverage_of_required": 0.0, "unexpected_imports": [],
        "missing_required": spec.required_primitives,
    }
    static_findings = (
        run_static_scan(workdir, spec.judge_dir / "static_scan.yaml")
        if workdir.exists() else []
    )
    metrics = {
        "identity": {
            "run_id": adir.parts[-5],
            "spec_id": spec.spec_id,
            "condition": condition,
            "attempt": attempt,
            "seed": seed,
            "model": emission.model,
            "temperature": emission.temperature,
            "kit_commit": _git_sha(),
            "mcp_config_hash": _mcp_config_hash() if condition == "kit" else "naked",
            "harness_version": HARNESS_VERSION,
            "brief_sha256": spec.brief_sha256,
        },
        "outcome": {
            "emit_status": emission.emit_status,
            "emit_error": emission.error,
            "boot_status": judge.boot_status,
            "final_score": judge.final_score,
            "tests_passed": judge.tests_passed,
            "tests_total": judge.tests_total,
            "per_layer": judge.per_layer,
            "per_bucket": judge.per_bucket,
            "judge_notes": judge.notes,
        },
        "efficiency": {
            "wall_clock_s": round(emission.wall_clock_s, 2),
            "input_tokens": emission.input_tokens,
            "output_tokens": emission.output_tokens,
            "cache_read_tokens": emission.cache_read_tokens,
            "cache_creation_tokens": emission.cache_creation_tokens,
        },
        "kit_attribution": attribution_info,
        "static_findings": [
            {
                "rule_id": f.rule_id, "severity": f.severity,
                "verdict": f.verdict, "matches": f.matches,
                "description": f.description,
            }
            for f in static_findings
        ],
        "extra": emission.extra,
    }
    (adir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=False))
    return metrics


def run_attempt(
    spec: Spec, adapter: MaestroAdapter, *,
    run_id: str, condition: str, attempt: int, seed: int,
) -> dict:
    adir = _attempt_dir(run_id, spec, condition, attempt)
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "brief.md").write_text(spec.brief, encoding="utf-8")
    workdir = adir / "emitted"
    emission = adapter.emit(spec, workdir, seed=seed)
    if emission.emit_status != "success":
        judge = JudgeResult(
            boot_status="skipped", boot_log_path=None,
            notes=f"judge skipped: emit_status={emission.emit_status}",
        )
    else:
        judge = run_judge(spec, workdir)
    # Snapshot the final emission for deterministic replay + fine-tuning harvest.
    if workdir.exists():
        snapshot_workdir(workdir, adir / "file_snapshots", label="final")
    return _write_metrics(
        adir, spec=spec, condition=condition, attempt=attempt, seed=seed,
        emission=emission, judge=judge,
    )


def run_all(
    specs: list[Spec], adapters: dict[str, MaestroAdapter], *,
    seeds: list[int], run_id: str | None = None, attempts_per_seed: int = 1,
) -> dict:
    run_id = run_id or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = RESULTS_ROOT / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    all_metrics: list[dict] = []
    # Attempt index is per-(spec, condition, seed) so DPO pairing across
    # conditions works on matching (spec, seed, attempt_within_seed).
    for spec in specs:
        for seed in seeds:
            for attempt_within in range(1, attempts_per_seed + 1):
                for condition, adapter in adapters.items():
                    m = run_attempt(
                        spec, adapter, run_id=run_id,
                        condition=condition, attempt=attempt_within,
                        seed=seed,
                    )
                    all_metrics.append(m)
                    outcome = m["outcome"]
                    print(
                        f"  {spec.spec_id:45} {condition:6} seed={seed:<10} "
                        f"attempt={attempt_within}  "
                        f"score={outcome['final_score']:6.2f}  "
                        f"({outcome['tests_passed']}/{outcome['tests_total']}, "
                        f"boot={outcome['boot_status']})"
                    )
    manifest = {
        "run_id": run_id, "harness_version": HARNESS_VERSION,
        "kit_commit": _git_sha(), "generated_at":
            datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "specs_count": len(specs), "attempts_total": len(all_metrics),
        "per_run": all_metrics,
    }
    (run_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))

    # Aggregate + publish. Keeping compute in publish.py for separation of concerns.
    from engine.bench.blind.publish import aggregate_and_write  # local import
    aggregate_and_write(run_root, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stub", action="store_true",
                        help="use StubAdapter fixtures instead of Claude CLI")
    parser.add_argument("--stub-fixture-root", type=Path,
                        default=SKILL_ROOT / "benchmarks" / "blind" / "_stub_fixtures",
                        help="where StubAdapter reads pre-baked emissions")
    parser.add_argument("--spec", action="append", default=None,
                        help="run only these spec_ids (repeatable)")
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--attempts", type=int, default=1,
                        help="attempts per (spec × condition × seed)")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    specs = discover_specs(SPECS_ROOT)
    if args.spec:
        keep = set(args.spec)
        specs = [s for s in specs if s.spec_id in keep]
    if not specs:
        print("no specs matched", file=sys.stderr)
        return 2

    if args.stub:
        adapters: dict[str, MaestroAdapter] = {
            "naked": StubAdapter(args.stub_fixture_root, name="naked"),
            "kit":   StubAdapter(args.stub_fixture_root, name="kit"),
        }
    else:
        naked_cfg = ClaudeCliConfig(model=args.model, mcp_config_path=None)
        kit_cfg = ClaudeCliConfig(model=args.model, mcp_config_path=MCP_CONFIG)
        adapters = {
            "naked": ClaudeCliAdapter(naked_cfg, name="naked"),
            "kit":   ClaudeCliAdapter(kit_cfg, name="kit"),
        }

    manifest = run_all(
        specs, adapters, seeds=args.seeds,
        run_id=args.run_id, attempts_per_seed=args.attempts,
    )
    print(f"\nrun_id={manifest['run_id']}  attempts={manifest['attempts_total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
