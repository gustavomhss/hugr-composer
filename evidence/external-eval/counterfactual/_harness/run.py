"""Counterfactual runner — same 10 specs, same model, NO HuGR access.

PRODUCT §1 implicit "cheaper than hand-coded" — relative claim only:
given the same LLM, having HuGR yields lower token cost / time / LOC
than hand-authoring from scratch. This harness measures the no-HuGR
baseline so the delta vs single_shot_benchmark is auditable.

Wave-H/I-1 status: SKELETON. Live LLM execution is deferred to the
48h pre-tag window per LAUNCH.md §2.0. Without API keys this script
writes an empty run_manifest with shape verification.

Usage (when ready):
    export ANTHROPIC_API_KEY=...
    python evidence/external-eval/counterfactual/_harness/run.py

Cost: ~$35-70 for 10 specs × 1 model at current pricing.
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
SPECS_DIR = ARTEFACT_DIR.parent / "single_shot_benchmark" / "specs"
BASELINE_PROMPT = HARNESS_DIR / "baseline_prompt.md"
TRANSCRIPTS = ARTEFACT_DIR / "transcripts"
RESULTS = ARTEFACT_DIR / "results.json"
MANIFEST = ARTEFACT_DIR / "run_manifest.json"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _drive_baseline_session(spec_path: pathlib.Path, transcript_dir: pathlib.Path) -> pathlib.Path:
    """Drive ONE no-HuGR Maestro session for the given spec.

    Implementation deferred to 48h pre-tag per LAUNCH.md §2.0. To wire:
    - Use Anthropic SDK with the SAME pinned model as single_shot.
    - Submit `BASELINE_PROMPT.read_text()` as system prompt — this prompt
      forbids HuGR access, instructing the model to hand-author.
    - Submit `spec_path.read_text()` as user message.
    - Persist full conversation transcript to `transcript_dir/transcript.jsonl`.
    - Return the path to the emitted project directory under
      `transcript_dir/project/`.
    - Capture token usage from response metadata for delta math.
    """
    raise NotImplementedError(
        "paid run deferred to 48h pre-tag window per LAUNCH.md §2.0; "
        "wire Anthropic SDK + token accounting before the tag cut."
    )


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — writing EMPTY run_manifest for shape verification.")
        _write_manifest(empty=True)
        return 0

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    specs = sorted(SPECS_DIR.glob("[0-9][0-9]-*.md"))
    if len(specs) < 10:
        print(f"FATAL: need 10 specs, found {len(specs)}", file=sys.stderr)
        return 2

    started = _iso_now()
    results = []
    for spec in specs:
        tdir = TRANSCRIPTS / spec.stem
        tdir.mkdir(exist_ok=True)
        try:
            project_dir = _drive_baseline_session(spec, tdir)
        except NotImplementedError as e:
            print(f"spec={spec.name}: {e}")
            return 3
        verdict = _grade(project_dir, spec)
        results.append({"spec": spec.name, **verdict})

    completed = _iso_now()
    RESULTS.write_text(json.dumps({"results": results}, indent=2))
    _write_manifest(empty=False, started=started, completed=completed)
    return 0


def _grade(project_dir: pathlib.Path, spec: pathlib.Path) -> dict:
    """Re-use single_shot's grader (same 4-check rubric)."""
    sys.path.insert(0, str(ARTEFACT_DIR.parent / "single_shot_benchmark" / "_harness"))
    from grade import grade as _g  # type: ignore
    import re
    spec_text = spec.read_text()
    m = re.search(r"## Acceptance criteria\s*\n((?:\s*-\s+.+\n?)+)", spec_text)
    acs = []
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if line.startswith("-"):
                acs.append(line.lstrip("- ").strip())
    return _g(project_dir, acs)


def _stable_hash_or_blank() -> str:
    cat = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / "engine" / "index" / "catalog.json"
    if not cat.exists():
        return ""
    d = json.loads(cat.read_text())
    return d.get("stable_hash", "")


def _baseline_prompt_hash() -> str:
    if not BASELINE_PROMPT.exists():
        return ""
    return _sha(BASELINE_PROMPT)


def _write_manifest(empty: bool, started: str = "", completed: str = "") -> None:
    manifest = {
        "commit": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "stable_hash": _stable_hash_or_blank(),
        "model": {
            "id": "" if empty else "anthropic:claude-opus-4-7-20260101",
            "params": {"temperature": 0, "top_p": 1, "seed": None},
        },
        "baseline_prompt_hash": _baseline_prompt_hash(),
        "run_started": started,
        "run_completed": completed,
        "cost_usd_estimate": 0.0,
        "results_file": "./results.json",
        "transcripts_dir": "./transcripts/",
        "_status": "empty-at-wave-I-1" if empty else "executed",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    sys.exit(main())
