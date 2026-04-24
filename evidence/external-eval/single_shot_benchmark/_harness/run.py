"""Single-shot benchmark runner skeleton.

Drives N Maestro sessions (one per spec) + collects transcripts +
invokes grade.py for each. Produces results.json and run_manifest.json.

Wave-H status: SKELETON only. Paid execution is deferred to the 48h
pre-tag window per LAUNCH.md §2.0. When invoked without API keys, this
script documents the bootstrap path and writes an empty run_manifest
so `reproduce.sh --verify` sees the expected file shape.

Usage (when ready to run for real):
    export ANTHROPIC_API_KEY=sk-...
    python evidence/external-eval/single_shot_benchmark/_harness/run.py

Cost: ~$50-100 for 10 specs × 1 model at current Claude pricing.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

HARNESS_DIR = pathlib.Path(__file__).resolve().parent
ARTEFACT_DIR = HARNESS_DIR.parent
SPECS_DIR = ARTEFACT_DIR / "specs"
TRANSCRIPT_DIR = ARTEFACT_DIR / "transcripts"
RESULTS = ARTEFACT_DIR / "results.json"
MANIFEST = ARTEFACT_DIR / "run_manifest.json"
PROMPT = HARNESS_DIR / "prompt.md"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _prompt_bundle_hash() -> str:
    h = hashlib.sha256()
    for p in sorted([PROMPT]):
        h.update(p.read_bytes())
    return h.hexdigest()


def _drive_session(spec_path: pathlib.Path, transcript_path: pathlib.Path) -> pathlib.Path:
    """Drive one Maestro session for the given spec. Returns emitted project dir.

    IMPLEMENTATION NOTE (Wave-H deferred): wire this to the Anthropic SDK
    using the system prompt in prompt.md, with the HuGR MCP tool
    manifest. Output the full transcript to transcript_path and the
    emitted project under a sibling `project_XX/` dir.
    """
    raise NotImplementedError(
        "paid run deferred to 48h pre-tag window per LAUNCH.md §2.0; "
        "wire this to the Anthropic SDK before the tag cut."
    )


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — writing EMPTY run_manifest for shape verification.")
        _write_manifest(empty=True)
        return 0

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    specs = sorted(SPECS_DIR.glob("[0-9][0-9]-*.md"))
    if len(specs) < 10:
        print(f"FATAL: need 10 specs, found {len(specs)}", file=sys.stderr)
        return 2

    started = _iso_now()
    results = []
    for spec in specs:
        trn = TRANSCRIPT_DIR / spec.stem
        trn.mkdir(exist_ok=True)
        try:
            project_dir = _drive_session(spec, trn)
        except NotImplementedError as e:
            print(f"spec {spec.name}: {e}")
            return 3
        verdict = _grade(project_dir, spec)
        results.append({"spec": spec.name, **verdict})

    completed = _iso_now()
    RESULTS.write_text(json.dumps({"results": results}, indent=2))
    _write_manifest(empty=False, started=started, completed=completed)
    return 0


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_manifest(empty: bool, started: str = "", completed: str = "") -> None:
    manifest = {
        "commit": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "stable_hash": _stable_hash_or_blank(),
        "model": {
            "id": "" if empty else "anthropic:claude-opus-4-7-20260101",
            "pinned_at": "",
            "params": {"temperature": 0, "top_p": 1, "seed": None},
        },
        "prompt_bundle_hash": _prompt_bundle_hash(),
        "tool_manifest_hash": "",
        "run_started": started,
        "run_completed": completed,
        "cost_usd_estimate": 0.0,
        "results_file": "./results.json",
        "transcripts_dir": "./transcripts/",
        "grader_version": _sha(HARNESS_DIR / "grade.py"),
        "judge_notes": "" if empty else "filled after run; reviewer reads transcripts",
        "_status": "empty-at-wave-H" if empty else "executed",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))


def _stable_hash_or_blank() -> str:
    cat = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / "engine" / "index" / "catalog.json"
    if not cat.exists():
        return ""
    d = json.loads(cat.read_text())
    return d.get("stable_hash", "")


def _grade(project_dir: pathlib.Path, spec: pathlib.Path) -> dict:
    from grade import grade as _g  # local import so shape test runs without paid deps
    acs = _extract_acs(spec.read_text())
    return _g(project_dir, acs)


def _extract_acs(spec_text: str) -> list[str]:
    import re
    m = re.search(r"## Acceptance criteria\s*\n((?:\s*-\s+.+\n?)+)", spec_text)
    if not m:
        return []
    return [l.strip().lstrip("- ").strip() for l in m.group(1).splitlines() if l.strip().startswith("-")]


if __name__ == "__main__":
    sys.exit(main())
