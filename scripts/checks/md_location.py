#!/usr/bin/env python3
"""Repo rule: narrative markdown lives in docs/, not scattered through the tree.

Concentrating docs keeps the source navigable and free of MAESTRO_SESSION / brief /
KNOWLEDGE / HANDOFF noise. A markdown file is allowed only if it is:
  - under docs/ (or another exempt top-level: .github/, _staging/, tools/), OR
  - inside a content directory (any path segment in CONTENT_SEGMENTS — these
    legitimately hold specs/eval/example/audit markdown), OR
  - one of the allowed convention basenames (README/SKILL/KNOWLEDGE/LLM/…).
Everything else — including stray narrative markdown in code packages or at the
repo root — is a violation.

Modes:
  - pre-commit (argv = changed files): only those files → blocks NEW noise.
  - manual/CI (no argv): scans all tracked .md → reports the backlog.
Exit 1 on any violation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

# Top-level dirs whose markdown is fine (matched at path start).
ROOT_EXEMPT_PREFIXES = ("docs/", ".github/", "_staging/", "tools/")
# Content dirs that legitimately hold markdown at any depth (matched per-segment).
CONTENT_SEGMENTS = {"benchmarks", "examples", "specs", "evidence", "audit"}
# Convention files that are allowed anywhere (skill/platform/standard conventions).
ALLOWED_BASENAMES = {
    "README.md",
    "SKILL.md",
    "KNOWLEDGE.md",
    "LLM.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE.md",
    "CLAUDE.md",
}
_IGNORE = (".venv", "site-packages", "emitted", "node_modules")


def _tracked_md() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=False
    ).stdout
    return [p for p in out.splitlines() if p]


def _is_violation(path: str) -> bool:
    norm = path.replace("\\", "/")
    if any(seg in norm for seg in _IGNORE):
        return False
    if norm.startswith(ROOT_EXEMPT_PREFIXES):
        return False
    p = PurePosixPath(norm)
    if any(seg in CONTENT_SEGMENTS for seg in p.parts):
        return False
    if p.name in ALLOWED_BASENAMES:
        return False
    return True


def main(argv: list[str]) -> int:
    candidates = [a for a in argv if a.endswith(".md")] if argv else _tracked_md()
    violations = [p for p in candidates if _is_violation(p)]
    if violations:
        print(
            "✗ md_location: narrative markdown outside docs/ (move it to docs/ or delete):"
        )
        for v in sorted(violations)[:25]:
            print(f"    {v}")
        if len(violations) > 25:
            print(f"    … and {len(violations) - 25} more")
        print(
            "  Rule: narrative .md lives in docs/; code packages keep only README/SKILL/KNOWLEDGE."
        )
        return 1
    print("✓ md_location: no stray narrative markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
