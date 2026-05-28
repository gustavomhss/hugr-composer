#!/usr/bin/env python3
"""Repo rule: never track virtualenvs, site-packages, emitted projects, or DBs.

These bloat the tree (we found a whole .venv12 on disk + emitted apps) and have
bitten us with disk-full incidents. .gitignore should prevent them; this is the
backstop that fails CI/commit if one slips through.

Matching is by PATH SEGMENT (case-insensitive) for directories and by exact file
EXTENSION for data files — never naive substring (so `foo.dbt` is fine and
`Emitted/` is still caught).

Exit 1 if any forbidden path is tracked.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

# Directory names that must never appear as a path segment (case-insensitive).
FORBIDDEN_DIR_SEGMENTS = {"site-packages", "emitted", "node_modules", "__pycache__"}
# Virtualenv dirs incl. numbered variants: .venv, venv, .venv12, venv3.12 …
_VENV_RE = re.compile(r"^\.?venv[\d.]*$")
# Exact file extensions that must never be tracked.
FORBIDDEN_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".pyc")

# Path prefixes whose contents are EXEMPT from the `emitted` segment rule —
# committed test DATA, not regenerated scratch. Mirrors the `.gitignore`
# negation `!**/benchmarks/blind/_stub_fixtures/**` (contract B3.7).
EXEMPT_PREFIXES = (
    "skills/SKILL-001-fastapi-production/benchmarks/blind/_stub_fixtures/",
)


def _is_forbidden(path: str) -> bool:
    # Honour the same exemption the .gitignore carries — the stub fixtures
    # legitimately contain `emitted/` subtrees as part of the B3.7 fixture
    # contract; they are checked-in test data, not generator scratch.
    p_norm = path.replace("\\", "/")
    if p_norm.startswith(EXEMPT_PREFIXES):
        return False
    p = PurePosixPath(p_norm)
    for raw in p.parts:
        s = raw.lower()
        if s in FORBIDDEN_DIR_SEGMENTS or _VENV_RE.match(s):
            return True
    return p.suffix.lower() in FORBIDDEN_SUFFIXES


def main(argv: list[str]) -> int:
    if argv:
        tracked = argv
    else:
        tracked = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=False
        ).stdout.splitlines()
    bad = [p for p in tracked if p and _is_forbidden(p)]
    if bad:
        print(
            f"✗ no_committed_venv: {len(bad)} forbidden artifact(s) tracked (add to .gitignore + git rm --cached):"
        )
        for p in sorted(bad)[:20]:
            print(f"    {p}")
        if len(bad) > 20:
            print(f"    … and {len(bad) - 20} more")
        return 1
    print("✓ no_committed_venv: no venvs/site-packages/emitted/db tracked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
