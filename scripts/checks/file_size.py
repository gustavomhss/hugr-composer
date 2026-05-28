#!/usr/bin/env python3
"""Repo rule: keep logic files small. Templates are data and are exempt.

Sweet spot ~300 LOC, hard cap 500 (file-level only — no per-function cap). A file
over the hard cap is a refactor signal (usually embedded code-templates that
belong in templates/*.py.tmpl). Emitted-code template files do not count.

  - WARN  > 300 LOC  (non-blocking, reported)
  - FAIL  > 500 LOC  (blocking)

Modes: pre-commit (argv = changed .py) or manual/CI (scan tracked .py).
Exit 1 if any non-exempt logic file exceeds the hard cap.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOFT_CAP = 300
HARD_CAP = 500
EXEMPT_TOKENS = (".venv", "site-packages", "/emitted/", "node_modules", "/templates/")
EXEMPT_SUFFIXES = (".py.tmpl", ".tmpl", ".j2", ".mustache")


def _tracked_py() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], capture_output=True, text=True, check=False
    ).stdout
    return out.splitlines()


def _exempt(path: str) -> bool:
    return any(t in path for t in EXEMPT_TOKENS) or path.endswith(EXEMPT_SUFFIXES)


def main(argv: list[str]) -> int:
    files = [a for a in argv if a.endswith(".py")] if argv else _tracked_py()
    warns: list[tuple[str, int]] = []
    fails: list[tuple[str, int]] = []
    for f in files:
        if _exempt(f) or not Path(f).is_file():
            continue
        n = sum(1 for _ in open(f, encoding="utf-8", errors="ignore"))
        if n > HARD_CAP:
            fails.append((f, n))
        elif n > SOFT_CAP:
            warns.append((f, n))
    for f, n in sorted(warns, key=lambda x: -x[1]):
        print(
            f"  ⚠ file_size: {f} = {n} LOC (> {SOFT_CAP} soft cap — consider splitting / externalizing templates)"
        )
    if fails:
        print(f"✗ file_size: {len(fails)} file(s) over the {HARD_CAP} LOC hard cap:")
        for f, n in sorted(fails, key=lambda x: -x[1]):
            print(f"    {f} = {n} LOC")
        return 1
    print(
        f"✓ file_size: no logic file over {HARD_CAP} LOC ({len(warns)} over soft cap)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
