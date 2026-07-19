"""Machine-verified repo inventory — emits INVENTORY.md at skill root.

Single source of truth for counts. Every number in CLAUDE.md, STATUS.md,
memory, and the ROADMAP must reconcile against this script's output.

Run:
    PYTHONPATH=. .venv/bin/python -m engine.inventory

This module is now a thin **skill-side adapter** over the generic
``hugr_core.inventory`` engine: the counting / rendering logic lives in the
shared core, and everything below is THIS skill's configuration (filesystem
anchors, adapt buckets, doc title). An ``InventoryConfig`` is assembled per call
from the module-level globals (so the behaviour is identical to the pre-lift
single-file engine, byte-for-byte — this feeds the B4.7 counts-sync gate).
"""

from __future__ import annotations

from pathlib import Path

from hugr_core.inventory import (
    InventoryConfig,
)
from hugr_core.inventory import (
    _count_dirs as _core_count_dirs,
)
from hugr_core.inventory import (
    _count_mcp_tools as _core_count_mcp_tools,
)
from hugr_core.inventory import (
    _count_primitive_dirs as _core_count_primitive_dirs,
)
from hugr_core.inventory import (
    _count_py as _core_count_py,
)
from hugr_core.inventory import (
    _count_registered_primitives as _core_count_registered_primitives,
)
from hugr_core.inventory import (
    collect as _core_collect,
)
from hugr_core.inventory import (
    render_markdown as _core_render_markdown,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]

# Re-export so existing imports
# (`from engine.inventory import collect, render_markdown, SKILL_ROOT`, the
# `_count_*` helpers, …) keep resolving.
__all__ = [
    "SKILL_ROOT",
    "collect",
    "render_markdown",
    "main",
    "_count_py",
    "_count_dirs",
    "_count_mcp_tools",
    "_count_registered_primitives",
    "_count_primitive_dirs",
]


def _cfg() -> InventoryConfig:
    """Snapshot this skill's paths into an InventoryConfig.

    Read fresh each call so a test that monkeypatches ``SKILL_ROOT`` sees the
    change reflected in ``collect`` / ``main``.

    Layout note: this is a *standalone* checkout — the skill IS the repo root,
    so ``examples/`` sits directly under ``root``. The pre-lift engine assumed a
    monorepo layout (``repo/skills/SKILL-.../`` with ``repo/examples``) and
    anchored examples at ``root.parent.parent``; in a standalone checkout that
    overshoots two levels to a non-existent path and silently counted 0 examples.
    """
    root = SKILL_ROOT
    return InventoryConfig(
        skill_root=root,
        repo_root=root,
        catalog_path=root / "engine" / "index" / "catalog.json",
        registry_path=root / "engine" / "primitives_by_concern.yaml",
        venous_root=root / "core" / "venous",
        staging_root=root / "core" / "venous" / "_staging",
        adapters_root=root / "core" / "venous" / "_adapters" / "fastapi",
        adapt_subdirs=("extend", "verify", "operate", "evolve", "proactive", "contracts"),
        examples_dir=root / "examples",
        specs_dir=root / "specs",
        benchmark_specs_dir=root / "benchmarks" / "specs",
        doc_title="SKILL-001 Inventory",
        # Name the marker explicitly: keeps this shim self-counted by the (loose,
        # pre-PR-B) `"MCP_TOOL" in text` scan exactly as the pre-lift single-file
        # engine was, so the rendered INVENTORY.md stays byte-identical.
        tool_marker="MCP_TOOL",
    )


# ---------------------------------------------------------------------------
# Thin skill-bound wrappers over the generic engine (preserve every public name)
# ---------------------------------------------------------------------------


def _count_py(root: Path, *, skip_tests: bool = True) -> int:
    return _core_count_py(_cfg(), root, skip_tests=skip_tests)


def _count_dirs(root: Path, *, depth: int = 1) -> int:
    return _core_count_dirs(root, depth=depth)


def _count_mcp_tools() -> int:
    return _core_count_mcp_tools(_cfg())


def _count_registered_primitives() -> int:
    return _core_count_registered_primitives(_cfg())


def _count_primitive_dirs(
    root: Path, exclude: set[str] | None = None, *, pascal_only: bool = False
) -> int:
    return _core_count_primitive_dirs(root, exclude, pascal_only=pascal_only)


def collect() -> dict:
    return _core_collect(_cfg())


def render_markdown(inv: dict) -> str:
    return _core_render_markdown(_cfg(), inv)


def main() -> None:
    inv = collect()
    out = SKILL_ROOT / "INVENTORY.md"
    out.write_text(render_markdown(inv), encoding="utf-8")
    print(f"wrote {out.relative_to(SKILL_ROOT)}")
    print(f"  MCP tools: {inv['mcp_tools_total']}")
    print(f"  registered primitives: {inv['venous_registered_total']}")
    print(
        f"  staged primitives: {inv['extracted_staged_total']}  (+{inv['extracted_quarantined']} quarantined)"
    )


if __name__ == "__main__":
    main()
