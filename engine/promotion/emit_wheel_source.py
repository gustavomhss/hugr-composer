"""Emit the `hugr_fastapi` wheel source from `core/venous/`.

Full, idempotent regeneration of the flattened package that generated apps
`import` at runtime. Called by the promotion pipeline after a primitive is
promoted, and standalone via:

    PYTHONPATH=. .venv/bin/python -m engine.promotion.emit_wheel_source [--dry-run]

The source tree (`core/venous/<ns>/<Name>/`) is an evidence bundle: impl +
protocol + contract + spec + generated corpus, with PascalCase dirs and
dual-path import shims. That is NOT import-clean as a flat package. This
module produces `hugr_fastapi/<ns>/<Name>.py` (impl) and
`hugr_fastapi/_protocols/<ns>/<Name>.py` (protocol interface), rewrites the
intra-skill import shims to the packaged names, and regenerates `__init__.py`
exports for every namespace — dropping the test/chaos/metamorphic corpus.

Layout emitted (matches packaging/hugr-fastapi/pyproject.toml `packages`):

    hugr_fastapi/
      __init__.py
      <ns>/
        __init__.py
        <Name>.py            # impl
      _protocols/
        <ns>/
          <Name>.py          # protocol interface
      py.typed

Import rewrites applied per file:
  - `from core.venous.<ns>.<Name>.<Name> import X` -> `from hugr_fastapi.<ns>.<Name> import X`
  - `from ..<Sibling>.<Sibling> import X`           -> `from hugr_fastapi.<ns>.<Sibling> import X`
  - `from <Sibling> import X` (bare, inside try/except shims) ->
    `from hugr_fastapi.<ns>.<Sibling> import X`

Public exports per namespace are harvested from each primitive's `__all__`
when present, else the same-named symbol that defines the primitive.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_ROOT = SKILL_ROOT / "core" / "venous"
WHEEL_ROOT = SKILL_ROOT / "packaging" / "hugr-fastapi"
PKG_ROOT = WHEEL_ROOT / "hugr_fastapi"

_SKIPPED_DIRS = {"_staging", "_adapters", "_ports", "__pycache__"}

# `from core.venous.<ns>.<Name>.<Name> import X` — full skill-path form.
_RE_FULL = re.compile(
    r"from core\.venous\.(?P<ns>[a-z][a-z0-9_]*)\."
    r"(?P<prim>[A-Z][A-Za-z0-9_]*)\."
    r"(?P<prim2>[A-Z][A-Za-z0-9_]*)\s+import"
)
# `from ..Sibling.Sibling import X` — relative form inside <ns>.
_RE_REL = re.compile(
    r"from \.\.(?P<prim>[A-Z][A-Za-z0-9_]*)\.(?P<prim2>[A-Z][A-Za-z0-9_]*)\s+import"
)


def iter_primitives() -> list[tuple[str, str, Path]]:
    """Return (ns, Name, impl_path) for every registered primitive."""
    found: list[tuple[str, str, Path]] = []
    for ns_dir in sorted(
        p for p in VENOUS_ROOT.iterdir() if p.is_dir() and p.name not in _SKIPPED_DIRS
    ):
        for prim_dir in sorted(ns_dir.iterdir()):
            if (
                prim_dir.is_dir()
                and not prim_dir.name.startswith("_")
                and prim_dir.name not in _SKIPPED_DIRS
            ):
                impl = prim_dir / f"{prim_dir.name}.py"
                if impl.exists():
                    found.append((ns_dir.name, prim_dir.name, impl))
    return found


def _rewrite(source: str, ns: str, siblings: frozenset[str]) -> str:
    """Rewrite intra-skill import shims to packaged hugr_fastapi names."""
    source = _RE_FULL.sub(
        lambda m: f"from hugr_fastapi.{m.group('ns')}.{m.group('prim2')} import", source
    )
    source = _RE_REL.sub(lambda m: f"from hugr_fastapi.{ns}.{m.group('prim2')} import", source)
    # Bare-name fallback inside try/except shims: `from Sibling import X`.
    # Rewrite any bare name that is a registered primitive in the SAME
    # namespace (a self-import of the current module is left alone — it is a
    # test-path shim that the packaged module never takes).
    for sibling in siblings:
        source = source.replace(
            f"from {sibling} import", f"from hugr_fastapi.{ns}.{sibling} import"
        )
    return source


def _public_names(impl: Path) -> list[str]:
    """Names to re-export for a primitive: __all__ else the same-named symbol."""
    tree = ast.parse(impl.read_text())
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return [el.value for el in node.value.elts if isinstance(el, ast.Constant)]
    # No __all__: the primitive's own symbol (class/function) carries the name.
    for node in tree.body:
        if (
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == impl.stem
        ):
            return [node.name]
    # Fall back to any module-level public class.
    classes = [
        n.name for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith("_")
    ]
    return classes


def emit(dry_run: bool = False) -> int:
    """Regenerate the full hugr_fastapi/ tree. Returns 0 on success."""
    prims = iter_primitives()
    if not prims:
        print("No primitives found under core/venous/", file=sys.stderr)  # noqa: T201
        return 1

    if PKG_ROOT.exists() and not dry_run:
        shutil.rmtree(PKG_ROOT)
    PKG_ROOT.mkdir(parents=True, exist_ok=True)

    namespaces: dict[str, list[tuple[str, list[str]]]] = {}
    copied = 0
    # Names of all registered primitives per namespace, for bare-name rewrites.
    sibling_sets: dict[str, frozenset[str]] = {}
    for s_ns, s_name, _unused_impl in prims:
        sibling_sets.setdefault(s_ns, set()).add(s_name)  # type: ignore[arg-type]
    sibling_sets = {k: frozenset(v) for k, v in sibling_sets.items()}

    for ns, name, impl in prims:
        ns_dir = PKG_ROOT / ns
        ns_dir.mkdir(parents=True, exist_ok=True)
        proto_dir = PKG_ROOT / "_protocols" / ns
        proto_dir.mkdir(parents=True, exist_ok=True)
        if not (PKG_ROOT / "_protocols" / "__init__.py").exists() and not dry_run:
            (PKG_ROOT / "_protocols" / "__init__.py").write_text(
                '"hugr-fastapi protocol interfaces — the catalog shape a generated '
                'app compiles against."\n'
            )
        if not (proto_dir / "__init__.py").exists() and not dry_run:
            (proto_dir / "__init__.py").write_text("")

        siblings = sibling_sets[ns] - {name}
        rewritten = _rewrite(impl.read_text(), ns, siblings)
        (ns_dir / f"{name}.py").write_text(rewritten)
        copied += 1

        proto = impl.with_name(f"{impl.stem}.protocol.py")
        if proto.exists():
            (proto_dir / proto.name).write_text(_rewrite(proto.read_text(), ns, siblings))

        namespaces.setdefault(ns, []).append((name, _public_names(impl)))

    _write_namespace_inits(namespaces, dry_run=dry_run)
    _write_root_init(namespaces, dry_run=dry_run)
    _write_py_typed(dry_run=dry_run)

    print(  # noqa: T201
        f"hugr_fastapi tree regenerated: {copied} primitives across {len(namespaces)} namespaces"
    )
    print(f"  -> {PKG_ROOT}")  # noqa: T201
    return 0


def _write_namespace_inits(
    namespaces: dict[str, list[tuple[str, list[str]]]], *, dry_run: bool
) -> None:
    for ns, prims in sorted(namespaces.items()):
        ns_dir = PKG_ROOT / ns
        body = [
            f'"""hugr-fastapi namespace: {ns} — re-exports of the registered primitives."""',
            "",
            "from __future__ import annotations",
            "",
        ]
        for name, public in prims:
            if public:
                body.append(f"from hugr_fastapi.{ns}.{name} import (")
                for sym in public:
                    body.append(f"    {sym},")
                body.append(")")
                body.append("")
        body.append("__all__ = [")
        for _, public in prims:
            for sym in public:
                body.append(f'    "{sym}",')
        body.append("]")
        body.append("")
        if not dry_run:
            (ns_dir / "__init__.py").write_text("\n".join(body))


def _write_root_init(namespaces: dict[str, list[tuple[str, list[str]]]], *, dry_run: bool) -> None:
    body = [
        '"hugr-fastapi — framework-free production primitives for generated FastAPI apps."',
        "",
        "from __future__ import annotations",
        "",
    ]
    for ns in sorted(namespaces):
        body.append(f"from hugr_fastapi import {ns} as {ns}")
    body.append("")
    body.append(f"__all__ = {sorted(namespaces)!r}")
    body.append("")
    if not dry_run:
        (PKG_ROOT / "__init__.py").write_text("\n".join(body))


def _write_py_typed(*, dry_run: bool) -> None:
    if not dry_run:
        (PKG_ROOT / "py.typed").write_text("partial\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate the hugr_fastapi wheel source.")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan without writing.")
    args = ap.parse_args()
    return emit(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
