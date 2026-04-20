"""Primitive attribution — which core.venous.* primitives did the agent import?

Scans every .py file in the emitted workdir for `from core.venous.<ns>.<Name>`
or `import core.venous.<ns>.<Name>`. Returns:

  - `imported`: set of primitive names actually imported
  - `required`: set declared in spec.metadata.required_primitives
  - `coverage_of_required`: |imported ∩ required| / |required|
  - `unexpected`: imported but not required (not a failure — kit may help
                  with complementary pairings)
"""
from __future__ import annotations

import ast
from pathlib import Path


def scan_primitives(workdir: Path) -> set[str]:
    """Parse every .py under workdir and extract core.venous.*.<Name> leaves."""
    found: set[str] = set()
    for py in workdir.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("core.venous."):
                    parts = node.module.split(".")
                    if len(parts) >= 3:
                        # core.venous.<ns>.<Name>  →  <Name>
                        # also handle `from core.venous.<ns> import <Name>`
                        if len(parts) >= 4:
                            found.add(parts[3])
                        else:
                            for alias in node.names:
                                found.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("core.venous."):
                        parts = alias.name.split(".")
                        if len(parts) >= 4:
                            found.add(parts[3])
    return found


def attribute(workdir: Path, required: list[str]) -> dict:
    imported = scan_primitives(workdir)
    req_set = set(required)
    covered = imported & req_set
    unexpected = imported - req_set
    return {
        "imported": sorted(imported),
        "required": sorted(req_set),
        "coverage_of_required": (
            round(len(covered) / len(req_set), 3) if req_set else 0.0
        ),
        "unexpected_imports": sorted(unexpected),
        "missing_required": sorted(req_set - imported),
    }
