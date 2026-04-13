"""Deep import audit: verify every imported NAME exists in its target module.

Goes beyond checking module paths exist — actually parses each target module
and verifies that every imported class/function/variable is defined there.
"""
import ast
import sys
from pathlib import Path
from collections import defaultdict


def get_defined_names(filepath: Path) -> set[str]:
    """Extract all top-level names defined in a Python file."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return set()

    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            # Re-exports count as defined names
            for alias in node.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name)
    return names


def resolve_module_path(root: Path, module: str) -> Path | None:
    """Resolve 'app.core.config' to a file path on disk.

    Tries multiple roots to support both package layouts:
    - Modern: project/app/core/config.py (app/ subdirectory)
    - Legacy: project/core/config.py (flat layout, app/ doesn't exist)
    """
    parts = module.split(".")

    # Roots to try, in priority order:
    # 1. The given root + the full module path (modern layout)
    # 2. The given root with 'app.' stripped (legacy flat layout)
    candidates: list[Path] = []

    # Modern: respect the full module path including 'app.'
    candidates.append(root / "/".join(parts[:-1]) / f"{parts[-1]}.py")
    candidates.append(root / "/".join(parts) / "__init__.py")
    candidates.append(root / ("/".join(parts) + ".py"))

    # Legacy: strip 'app.' if present
    if module.startswith("app."):
        legacy_parts = module[4:].split(".")
        candidates.append(root / "/".join(legacy_parts[:-1]) / f"{legacy_parts[-1]}.py")
        candidates.append(root / "/".join(legacy_parts) / "__init__.py")
        candidates.append(root / ("/".join(legacy_parts) + ".py"))

    for filepath in candidates:
        if filepath.exists():
            return filepath

    return None


def audit(root: Path) -> list[str]:
    """Run the deep import audit."""
    errors = []
    warnings = []

    for py_file in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError as e:
            errors.append(f"SYNTAX: {py_file.relative_to(root)}: {e}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module or not node.module.startswith("app."):
                continue
            if node.level > 0:  # relative imports
                continue

            target_path = resolve_module_path(root, node.module)
            if target_path is None:
                errors.append(
                    f"{py_file.relative_to(root)}:{node.lineno}: "
                    f"MODULE NOT FOUND: {node.module}"
                )
                continue

            defined = get_defined_names(target_path)

            for alias in node.names:
                name = alias.name
                if name == "*":
                    continue
                if name not in defined:
                    errors.append(
                        f"{py_file.relative_to(root)}:{node.lineno}: "
                        f"NAME NOT FOUND: '{name}' not defined in {node.module} "
                        f"(available: {sorted(defined)[:10]}{'...' if len(defined) > 10 else ''})"
                    )

    return errors


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    errors = audit(root)

    if errors:
        print(f"\n{'='*60}")
        print(f"  DEEP IMPORT AUDIT: {len(errors)} ERROR(S)")
        print(f"{'='*60}\n")
        for e in errors:
            print(f"  ❌ {e}")
        print()
        sys.exit(1)
    else:
        print(f"\n  ✅ DEEP IMPORT AUDIT: ALL imported names verified")
        print(f"     Every 'from app.X import Y' → Y exists in X\n")
