"""Cross-model FNF runner — 10 specs × 3 models, single-shot, parallel sessions.

PRODUCT §1: kit is model-agnostic. Concretely: same blind specs scored
against Claude Opus + GPT-5 + Gemini 2.5 should yield ≤10% cross-model
variance (CV%). Higher = the user's model choice drives the result, not
the kit.

The harness re-uses single_shot_benchmark/_harness/grade.py for the 4-check
rubric. It uses the SAME prompt bundle as single_shot (symlinked from
prompt.md). The ONLY axis varied is the model.

Wave-H/I-1 status: SKELETON. Live LLM execution is deferred to the
48h pre-tag window per LAUNCH.md §2.0. Without API keys this script
writes an empty run_manifest with shape verification.

Usage (when ready):
    export ANTHROPIC_API_KEY=...
    export OPENAI_API_KEY=...
    export GOOGLE_API_KEY=...
    python evidence/external-eval/cross_model_fnf/_harness/run.py

Cost: ~$75-150 for 10 specs × 3 models at current pricing.
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
SHARED_PROMPT = ARTEFACT_DIR.parent / "single_shot_benchmark" / "_harness" / "prompt.md"
TRANSCRIPTS = ARTEFACT_DIR / "transcripts"
RESULTS = ARTEFACT_DIR / "results.json"
VARIANCE = ARTEFACT_DIR / "variance_report.json"
MANIFEST = ARTEFACT_DIR / "run_manifest.json"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

MODELS = [
    {
        "id": "anthropic:claude-opus-4-7-20260101",
        "env": "ANTHROPIC_API_KEY",
        "label": "claude_opus_4_7",
    },
    {
        "id": "openai:gpt-5.1-pro-20260401",
        "env": "OPENAI_API_KEY",
        "label": "gpt_5_1_pro",
    },
    {
        "id": "google:gemini-2.5-ultra-20260215",
        "env": "GOOGLE_API_KEY",
        "label": "gemini_2_5_ultra",
    },
]


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _prompt_bundle_hash() -> str:
    if not SHARED_PROMPT.exists():
        return ""
    return _sha(SHARED_PROMPT)


def _drive_session(
    spec_path: pathlib.Path, model: dict, transcript_dir: pathlib.Path
) -> pathlib.Path:
    """Drive ONE agent session for the given spec + model.

    Implementation deferred to 48h pre-tag per LAUNCH.md §2.0. To wire:
    - Use the provider SDK matching `model["id"]` prefix.
    - Submit `SHARED_PROMPT.read_text()` as system prompt.
    - Submit `spec_path.read_text()` as user message.
    - Persist full conversation transcript to `transcript_dir/transcript.jsonl`.
    - Return the path to the emitted project directory under
      `transcript_dir/project/`.
    """
    raise NotImplementedError(
        "paid run deferred to 48h pre-tag window per LAUNCH.md §2.0; "
        "wire SDKs for the 3 providers before the tag cut."
    )


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _all_keys_present() -> bool:
    return all(os.environ.get(m["env"]) for m in MODELS)


def main() -> int:
    # Codex v9 closure: was fail-open when keys missing. Now requires
    # --shape-only flag for schema-verification-only mode.
    shape_only = "--shape-only" in sys.argv
    if not _all_keys_present():
        missing = [m["env"] for m in MODELS if not os.environ.get(m["env"])]
        if shape_only:
            print(f"--shape-only: missing keys {missing}; writing EMPTY run_manifest.")
            _write_manifest(empty=True)
            return 0
        print(
            f"FATAL: missing API keys: {missing}. Pass --shape-only for schema verification only.",
            file=sys.stderr,
        )
        return 2

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    specs = sorted(SPECS_DIR.glob("[0-9][0-9]-*.md"))
    if len(specs) < 10:
        print(f"FATAL: need 10 specs, found {len(specs)}", file=sys.stderr)
        return 2

    started = _iso_now()
    results = []
    for spec in specs:
        for m in MODELS:
            tdir = TRANSCRIPTS / f"{spec.stem}__{m['label']}"
            tdir.mkdir(exist_ok=True)
            try:
                project_dir = _drive_session(spec, m, tdir)
            except NotImplementedError as e:
                print(f"spec={spec.name} model={m['label']}: {e}")
                return 3
            verdict = _grade(project_dir, spec)
            results.append({"spec": spec.name, "model": m["label"], **verdict})

    completed = _iso_now()
    RESULTS.write_text(json.dumps({"results": results}, indent=2))
    _write_manifest(empty=False, started=started, completed=completed)

    # Post-process variance
    from variance import compute as variance_compute

    VARIANCE.write_text(json.dumps(variance_compute(RESULTS), indent=2))
    return 0


def _grade(project_dir: pathlib.Path, spec: pathlib.Path) -> dict:
    """Re-use single_shot's grader."""
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
    cat = (
        REPO_ROOT
        / "skills"
        / "SKILL-001-fastapi-production"
        / "engine"
        / "index"
        / "catalog.json"
    )
    if not cat.exists():
        return ""
    d = json.loads(cat.read_text())
    return d.get("stable_hash", "")


def _write_manifest(empty: bool, started: str = "", completed: str = "") -> None:
    manifest = {
        "commit": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "stable_hash": _stable_hash_or_blank(),
        "models": [
            {"id": "" if empty else m["id"], "label": m["label"]} for m in MODELS
        ],
        "prompt_bundle_hash": _prompt_bundle_hash(),
        "tool_manifest_hash": "",
        "run_started": started,
        "run_completed": completed,
        "cost_usd_estimate": 0.0,
        "results_file": "./results.json",
        "transcripts_dir": "./transcripts/",
        "variance_report_file": "./variance_report.json",
        "_status": "empty-at-wave-I-1" if empty else "executed",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    sys.exit(main())
