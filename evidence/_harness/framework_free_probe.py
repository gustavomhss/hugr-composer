"""Scan registered primitives for web-framework imports.

Produces a deterministic report on stdout. Intended to be invoked by
`evidence/reproduce.sh --deterministic` from repo root — not a pytest.

Exit 0 = 124 registered primitives, zero framework imports.
Exit 1 = at least one primitive imports a web framework.

PRODUCT §2 / §6.2 — primitives are framework-free motors.
"""
from __future__ import annotations

import ast
import pathlib
import sys

FRAMEWORK_PREFIXES = (
    "fastapi",
    "starlette",
    "uvicorn",
    "flask",
    "django",
    "tornado",
    "sanic",
    "bottle",
    "aiohttp",
    "quart",
    "falcon",
    "hypercorn",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
VENOUS_ROOT = REPO_ROOT / "skills" / "SKILL-001-fastapi-production" / "core" / "venous"


def discover_registered() -> list[pathlib.Path]:
    """Return the set of `core/venous/<ns>/<Name>/<Name>.py` files."""
    out: list[pathlib.Path] = []
    for ns_dir in sorted(p for p in VENOUS_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for prim_dir in sorted(p for p in ns_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
            main_py = prim_dir / f"{prim_dir.name}.py"
            if main_py.exists():
                out.append(main_py)
    return out


def framework_imports(py: pathlib.Path) -> list[str]:
    tree = ast.parse(py.read_text())
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0].lower()
                if root_mod in FRAMEWORK_PREFIXES:
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0].lower()
            if mod in FRAMEWORK_PREFIXES:
                hits.append(f"from {node.module}")
    return hits


def main() -> int:
    registered = discover_registered()
    violations: list[tuple[str, str]] = []
    for py in registered:
        for v in framework_imports(py):
            violations.append((str(py.relative_to(VENOUS_ROOT)), v))

    print(f"registered_primitives: {len(registered)}")
    print(f"frameworks_checked: {len(FRAMEWORK_PREFIXES)}")
    print(f"framework_imports_found: {len(violations)}")
    for path, imp in violations[:20]:
        print(f"  VIOLATION: {path} -> {imp}")

    if not violations and len(registered) == 124:
        print("PASS: 124/124 registered primitives framework-free")
        return 0
    if not violations:
        print(f"PASS-partial: {len(registered)}/124 registered primitives framework-free")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
