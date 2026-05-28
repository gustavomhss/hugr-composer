"""Signal detection for §A12 compliance.

A staged primitive is §A12-eligible for promotion only if ONE of:
    (a) a benchmark spec references the concept the primitive addresses;
    (b) a registered tool imports it (direct caller);
    (c) a ratified triage-pass entry covers it (handled in the ledger).

This module implements (a) and (b) via the following authoritative sources:

* Catalog — `engine/index/catalog.json` lists tools with `primitives_used`.
  If a tool's `primitives_used` mentions the staged primitive's name, that
  is a TOOL_IMPORT signal.
* `_origin.json` — every staged primitive records which tool produced it.
  If that tool still lives in the catalog, the origin itself is a signal.
* Generators and modules — scanned for `from core.venous.*.<Name>` imports.
* Benchmark specs — scanned under `benchmarks/specs/**/*.md` for direct
  mentions by name or by a small concept dictionary (best-effort; emits a
  BENCHMARK_REF signal that still needs human confirmation).

All signal detection is read-only. No file write side effects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine.promotion.schemas import Signal, SignalKind

SKILL_ROOT = Path(__file__).resolve().parents[2]


def _load_catalog() -> dict:
    p = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not p.exists():
        return {"tools": []}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_origin(primitive_dir: Path) -> dict | None:
    origin = primitive_dir / "_origin.json"
    if not origin.exists():
        return None
    try:
        return json.loads(origin.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def detect_tool_imports(primitive_name: str, catalog: dict) -> list[Signal]:
    """Tools whose catalog entry lists this primitive in `primitives_used`."""
    out: list[Signal] = []
    for tool in catalog.get("tools", []):
        used = tool.get("primitives_used") or []
        if primitive_name in used:
            out.append(
                Signal(
                    kind=SignalKind.TOOL_IMPORT,
                    source=tool.get("module_path", tool.get("name", "")),
                    detail=(
                        f"Tool `{tool.get('name', '')}` declares "
                        f"imports_primitives including `{primitive_name}`."
                    ),
                )
            )
    return out


def detect_origin_tool(primitive_dir: Path, catalog: dict) -> Signal | None:
    """If the origin tool still lives in the catalog, that's a GENERATOR_REF."""
    origin = _load_origin(primitive_dir)
    if not origin:
        return None
    origin_tool = origin.get("tool") or origin.get("candidate", {}).get("tool") or ""
    if not origin_tool:
        return None
    # The origin path is tool-relative (e.g. "api_design/add_api_deprecation.py").
    # Match against catalog module_path endings.
    for tool in catalog.get("tools", []):
        mp = tool.get("module_path", "")
        if mp.endswith(origin_tool) or origin_tool in mp:
            return Signal(
                kind=SignalKind.GENERATOR_REF,
                source=mp,
                detail=(
                    f"Primitive was extracted from `{mp}` (still in catalog); "
                    "origin tool remains a live caller pattern."
                ),
            )
    return None


_SOURCE_IMPORT_RE = re.compile(r"from\s+core\.venous\.[a-z_]+\.([A-Z][A-Za-z0-9_]+)")


def detect_source_imports(primitive_name: str, roots: list[Path]) -> list[Signal]:
    """Scan .py trees for `from core.venous.<ns>.<primitive_name>` imports."""
    out: list[Signal] = []
    pattern = re.compile(rf"from\s+core\.venous\.[a-z_]+\.{re.escape(primitive_name)}\b")
    for root in roots:
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts or "_staging" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(text):
                out.append(
                    Signal(
                        kind=SignalKind.MODULE_REF,
                        source=str(py.relative_to(SKILL_ROOT)),
                        detail=(
                            f"File imports `core.venous.*.{primitive_name}` "
                            "directly — staged primitive has a live caller."
                        ),
                    )
                )
    return out


def detect_benchmark_refs(primitive_name: str, benchmark_dir: Path) -> list[Signal]:
    """Best-effort: name mentions in benchmark spec .md files."""
    if not benchmark_dir.exists():
        return []
    out: list[Signal] = []
    pat = re.compile(rf"\b{re.escape(primitive_name)}\b")
    for spec in benchmark_dir.rglob("*.md"):
        try:
            text = spec.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pat.search(text):
            out.append(
                Signal(
                    kind=SignalKind.BENCHMARK_REF,
                    source=str(spec.relative_to(SKILL_ROOT)),
                    detail=(
                        f"Spec `{spec.name}` mentions `{primitive_name}` "
                        "by name — benchmark-signal candidate (verify manually "
                        "before treating as §A12(a))."
                    ),
                )
            )
    return out


def collect_signals(primitive_name: str, primitive_dir: Path, catalog: dict) -> list[Signal]:
    """One-shot signal collection for a single primitive."""
    out: list[Signal] = []
    out.extend(detect_tool_imports(primitive_name, catalog))
    origin_signal = detect_origin_tool(primitive_dir, catalog)
    if origin_signal:
        out.append(origin_signal)
    roots = [
        SKILL_ROOT / "generators",
        SKILL_ROOT / "modules",
        SKILL_ROOT / "adapt",
        SKILL_ROOT / "benchmarks" / "specs",
    ]
    out.extend(detect_source_imports(primitive_name, roots))
    out.extend(detect_benchmark_refs(primitive_name, SKILL_ROOT / "benchmarks" / "specs"))
    return out
