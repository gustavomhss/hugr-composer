#!/usr/bin/env python3
"""Extractor: lift top-ranked candidates into a staging area for review.

Reads `primitive_candidates_ranked.json` (produced by `classify.py`) and
writes each qualifying candidate's raw source into
`core/venous/_extracted/<TopicGuess>/<Name>/` — one directory per primitive.

This is STAGE 1 of extraction: pure lifting, no HuGR shell yet. Human review
happens here:
  - Is the extracted class/function a real primitive or a tool-specific helper?
  - What namespace does it belong to? (Auto-guessed from the source tool's
    folder, then confirmed.)
  - What Protocol surface should wrap it?
  - Does it already exist in the derived catalog? (dedupe against
    `core/venous/*/*/` manifests — see `dedupe.py`, next pass.)

Only after human-review does STAGE 2 wrap it with the HuGR shell
(Protocol + invariant_bindings + observability_schema) and run the
minimal T0/T1/T7 gate.

Controlled by `--top N` flag (default 50). Deterministic — rerunning
overwrites the staging area.
"""

from __future__ import annotations

import argparse
import ast
import json
import textwrap
from pathlib import Path
from typing import Any

_RANKED_PATH = Path(__file__).resolve().parent / "primitive_candidates_ranked.json"
_EXTEND_DIR = Path(__file__).resolve().parents[2] / "adapt" / "extend"
_STAGE_DIR = Path(__file__).resolve().parents[2] / "core" / "venous" / "_extracted"


_FOLDER_TO_NAMESPACE: dict[str, str] = {
    # Tool folder → best-guess venous namespace for the extracted primitive.
    # Human can override in stage 2.
    "auth_access": "auth",
    "crud_data": "data",
    "api_design": "api",
    "infrastructure": "resiliency",
    "realtime": "api",
    "testing_tools": "extras",
}


def _guess_namespace(tool_rel: str) -> str:
    folder = tool_rel.split("/", 1)[0]
    return _FOLDER_TO_NAMESPACE.get(folder, "extras")


def _extract_source(tool_path: Path, candidate_name: str) -> str | None:
    """Return the raw source of the named class/function from inside any
    string template in the tool. Returns dedented Python source."""
    try:
        tree = ast.parse(tool_path.read_text())
    except SyntaxError:
        return None

    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                continue
            dedented = textwrap.dedent(child.value)
            try:
                inner = ast.parse(dedented)
            except SyntaxError:
                continue
            for node in inner.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == candidate_name:
                        return ast.unparse(node)
    # Fall back to tool-file top-level.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == candidate_name:
                return ast.unparse(node)
    return None


_EXTRACT_NOTE_TEMPLATE = """\
# EXTRACTED STAGING — NOT YET SOTA

**Source tool:** `adapt/extend/{tool}`
**Primitive name:** `{name}`
**Kind:** `{kind}`
**Score:** {score}
**Guessed namespace:** `{namespace}`

Originally embedded as a string template that the tool writes into scaffolded
projects. Lifted here as raw Python source for review.

## Human-review checklist

- [ ] Is this a genuine reusable primitive, or tool-specific?
- [ ] Does it duplicate a catalog-derived primitive (e.g. `core/venous/...`)?
- [ ] What Protocol surface wraps it?
- [ ] What invariants does it enforce? File `invariant_bindings.json`.
- [ ] What observability signals does it emit? File `observability_schema.json`.
- [ ] Namespace correct? Original guess is derived from the source tool's
      folder.
- [ ] Imports: templates drop implicit FastAPI/SQLAlchemy/Redis references —
      these must be resolved and sometimes stubbed.

## When promoted

Move the directory from `core/venous/_extracted/<Name>/` to
`core/venous/<namespace>/<Name>/`, add the HuGR shell, and run the minimal
gate:

```
PYTHONPATH=. python -m engine.check_primitive \\
  --primitive-dir core/venous/{namespace}/{name} \\
  --catalog-entry docs/research/outputs/EXTRACTED.json \\
  --maturity emerging --builder-agent 99 \\
  --invariant-bindings core/venous/{namespace}/{name}/invariant_bindings.json
```
"""


def _write_staged_primitive(cand: dict[str, Any]) -> Path:
    name = cand["name"]
    tool_rel = cand["tool"]
    namespace = _guess_namespace(tool_rel)
    target = _STAGE_DIR / namespace / name
    target.mkdir(parents=True, exist_ok=True)

    source = _extract_source(_EXTEND_DIR / tool_rel, name)
    if source is None:
        source = f"# EXTRACT FAILED: could not locate {name!r} in {tool_rel}\n"

    (target / f"{name}.py").write_text(source + "\n")
    # README.md intentionally NOT written here — `wrap_shell.py` emits the
    # canonical `{name}.md` that includes provenance + review checklist.
    _ = _EXTRACT_NOTE_TEMPLATE  # kept for reference in case of standalone staging runs
    (target / "_origin.json").write_text(json.dumps({
        "tool": tool_rel,
        "candidate": {k: v for k, v in cand.items() if k not in ("signals",)},
    }, indent=2))
    return target


def run(top_n: int, *, force_clean: bool = False) -> list[Path]:
    ranked = json.loads(_RANKED_PATH.read_text())
    qualifying = [r for r in ranked if not r["disqualified"]]
    _STAGE_DIR.mkdir(parents=True, exist_ok=True)

    # NEVER blow away human edits. Only wipe the staging dir when the caller
    # opts in via `--force-clean`; otherwise we write/overwrite candidate
    # sources in place and skip directories that look edited. Re-runnability
    # is preserved; human review is not destroyed.
    if force_clean:
        import shutil
        if _STAGE_DIR.exists():
            shutil.rmtree(_STAGE_DIR)
        _STAGE_DIR.mkdir(parents=True)

    written: list[Path] = []
    for cand in qualifying[:top_n]:
        tool_rel = cand["tool"]
        ns = _guess_namespace(tool_rel)
        target_dir = _STAGE_DIR / ns / cand["name"]
        # Skip if the staged primitive has been edited (marker: contract.json
        # exists and lacks REPLACE_ME — humans started curating).
        contract = target_dir / f"{cand['name']}.contract.json"
        if contract.exists() and "REPLACE_ME" not in contract.read_text():
            written.append(target_dir)
            continue
        target = _write_staged_primitive(cand)
        written.append(target)
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract top-N primitives to staging.")
    parser.add_argument("--top", type=int, default=50,
                        help="How many top-ranked candidates to stage (default 50).")
    parser.add_argument("--force-clean", action="store_true",
                        help="Destroy _extracted/ first. DESTROYS human edits.")
    args = parser.parse_args()
    paths = run(args.top, force_clean=args.force_clean)
    print(f"Staged {len(paths)} primitives under {_STAGE_DIR.relative_to(Path.cwd())}:")
    for p in paths[:20]:
        print(f"  {p.relative_to(Path.cwd())}")
    if len(paths) > 20:
        print(f"  ... ({len(paths) - 20} more)")
