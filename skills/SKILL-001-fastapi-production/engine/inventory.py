"""Machine-verified repo inventory — emits INVENTORY.md at skill root.

Single source of truth for counts. Every number in CLAUDE.md, STATUS.md,
memory, and the ROADMAP must reconcile against this script's output.

Run:
    PYTHONPATH=. .venv/bin/python -m engine.inventory
"""
from __future__ import annotations

import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


def _count_py(root: Path, *, skip_tests: bool = True) -> int:
    if not root.exists():
        return 0
    n = 0
    for p in root.rglob("*.py"):
        s = p.name
        if "__pycache__" in p.parts:
            continue
        if skip_tests and (s.startswith("test_") or s == "conftest.py"):
            continue
        if s == "__init__.py":
            continue
        n += 1
    return n


def _count_dirs(root: Path, *, depth: int = 1) -> int:
    if not root.exists():
        return 0
    if depth == 1:
        return sum(1 for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
    return sum(
        1
        for p in root.rglob("*")
        if p.is_dir()
        and len(p.relative_to(root).parts) == depth
        and not any(pt.startswith(("_quarantine", "__pycache__")) for pt in p.relative_to(root).parts[:-1])
    )


def _count_mcp_tools() -> int:
    n = 0
    for py in SKILL_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or "_extracted" in py.parts:
            continue
        try:
            if "MCP_TOOL" in py.read_text(encoding="utf-8"):
                n += 1
        except (OSError, UnicodeDecodeError):
            continue
    return n


def _count_registered_primitives() -> int:
    p = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.startswith("- name:"))


def _count_primitive_dirs(root: Path, exclude: set[str] | None = None) -> int:
    exclude = exclude or set()
    if not root.exists():
        return 0
    n = 0
    for p in root.rglob("*"):
        if not p.is_dir():
            continue
        if any(part in exclude or part.startswith("_") for part in p.relative_to(root).parts[:-1]):
            continue
        if p.name.startswith(("_", ".")):
            continue
        # A "primitive dir" has a <Name>.py matching its directory name
        if (p / f"{p.name}.py").exists():
            n += 1
    return n


def collect() -> dict:
    R = SKILL_ROOT

    # adapt/ breakdown
    adapt_subdirs = ["extend", "verify", "operate", "evolve", "proactive", "contracts"]
    adapt: dict[str, int] = {}
    for sub in adapt_subdirs:
        adapt[sub] = _count_py(R / "adapt" / sub)

    # adapt/extend/ subdomains
    extend_subdomains: dict[str, int] = {}
    ext_root = R / "adapt" / "extend"
    if ext_root.exists():
        for p in sorted(ext_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                extend_subdomains[p.name] = _count_py(p)

    # generators/
    generators: dict[str, int] = {}
    gen_root = R / "generators"
    if gen_root.exists():
        for p in sorted(gen_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                generators[p.name] = _count_py(p)

    # modules/
    modules: dict[str, int] = {}
    mod_root = R / "modules"
    if mod_root.exists():
        for p in sorted(mod_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                modules[p.name] = _count_py(p)

    # core/venous — registered primitives per namespace (excluding _extracted, _adapters)
    venous_ns: dict[str, int] = {}
    venous_root = R / "core" / "venous"
    if venous_root.exists():
        for p in sorted(venous_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                venous_ns[p.name] = _count_primitive_dirs(p)

    # Adapters
    adapter_count = 0
    adapt_root = R / "core" / "venous" / "_adapters" / "fastapi"
    if adapt_root.exists():
        adapter_count = sum(
            1 for p in adapt_root.glob("*.py")
            if not p.name.startswith(("_", "test_"))
        )

    # _extracted staged
    extracted_ns: dict[str, int] = {}
    ext_staged = R / "core" / "venous" / "_extracted"
    if ext_staged.exists():
        for p in sorted(ext_staged.iterdir()):
            if p.is_dir():
                extracted_ns[p.name] = _count_primitive_dirs(p)

    # catalog.json counts
    catalog_path = R / "engine" / "index" / "catalog.json"
    catalog_counts = {"tools": 0, "primitives": 0, "recipes": 0}
    if catalog_path.exists():
        try:
            cat = json.loads(catalog_path.read_text())
            for k in catalog_counts:
                catalog_counts[k] = len(cat.get(k, []))
        except (OSError, json.JSONDecodeError):
            pass

    # Examples + specs
    # Count only populated example directories — empty scaffolds don't count.
    def _has_files(d: Path) -> bool:
        return any(f.is_file() for f in d.rglob("*") if ".pycache" not in f.parts)

    examples_dir = R / "examples"
    examples_populated = 0
    examples_empty = 0
    if examples_dir.exists():
        for p in examples_dir.iterdir():
            if not (p.is_dir() and not p.name.startswith((".", "_"))):
                continue
            if _has_files(p):
                examples_populated += 1
            else:
                examples_empty += 1
    examples = examples_populated
    specs = sum(1 for p in (R / "specs").glob("*.md") if not p.name.startswith(("README", "RESUME")))
    benchmark_specs = sum(
        1 for p in (R / "benchmarks" / "specs").rglob("*.md")
        if p.name.upper() != "README.MD"
    ) if (R / "benchmarks" / "specs").exists() else 0

    return {
        "mcp_tools_total": _count_mcp_tools(),
        "catalog": catalog_counts,
        "adapt": adapt,
        "adapt_total": sum(adapt.values()),
        "extend_subdomains": extend_subdomains,
        "generators": generators,
        "generators_total": sum(generators.values()),
        "modules": modules,
        "modules_total": sum(modules.values()),
        "venous_registered": venous_ns,
        "venous_registered_total": sum(venous_ns.values()),
        "adapters_fastapi": adapter_count,
        "extracted_staged": extracted_ns,
        "extracted_staged_total": sum(v for k, v in extracted_ns.items() if k != "_quarantine"),
        "extracted_quarantined": extracted_ns.get("_quarantine", 0),
        "examples": examples,
        "examples_empty": examples_empty,
        "specs": specs,
        "benchmark_specs": benchmark_specs,
    }


def render_markdown(inv: dict) -> str:
    def _table(d: dict[str, int], k_label: str, v_label: str = "count") -> str:
        lines = [f"| {k_label} | {v_label} |", "|---|---:|"]
        for k, v in d.items():
            lines.append(f"| `{k}` | {v} |")
        return "\n".join(lines)

    return f"""# SKILL-001 Inventory — Machine-Verified

> Generated by `python -m engine.inventory`. Every claim in CLAUDE.md,
> STATUS.md, SKILL.md, memory, ROADMAP must reconcile against this file.
> Drift = audit bug.

## Headline

- **{inv['mcp_tools_total']} files carry `MCP_TOOL` metadata** (Maestro-visible surface).
- **Catalog:** {inv['catalog']['tools']} tools + {inv['catalog']['primitives']} primitives + {inv['catalog']['recipes']} recipes.
- **{inv['venous_registered_total']} registered primitives** (`core/venous/<ns>/<Name>/`).
- **{inv['extracted_staged_total']} staged primitives** in `_extracted/` (plus {inv['extracted_quarantined']} quarantined).
- **{inv['adapters_fastapi']} FastAPI adapters** (production-wired).
- **{inv['modules_total']} `modules/` packages** (pre-built feature bundles).
- **{inv['examples']} populated examples** ({inv['examples_empty']} empty scaffolds), {inv['specs']} specs, {inv['benchmark_specs']} benchmark specs.

---

## 1. adapt/ — {inv['adapt_total']} tools

{_table(inv['adapt'], 'bucket')}

### adapt/extend/ sub-domains ({sum(inv['extend_subdomains'].values())} tools)

{_table(inv['extend_subdomains'], 'domain')}

## 2. generators/ — {inv['generators_total']} tools

{_table(inv['generators'], 'category')}

## 3. modules/ — {inv['modules_total']} modules

{_table(inv['modules'], 'module')}

## 4. core/venous — registered primitives ({inv['venous_registered_total']})

{_table(inv['venous_registered'], 'namespace')}

Plus **{inv['adapters_fastapi']} FastAPI adapters** under `core/venous/_adapters/fastapi/`.

## 5. core/venous/_extracted — staged primitives ({inv['extracted_staged_total']} + {inv['extracted_quarantined']} quarantined)

{_table(inv['extracted_staged'], 'namespace')}

Staged primitives have HuGR shell (contract.json, protocol, md, tests,
dashboard) but carry `REPLACE_ME` stubs — promote via extraction pipeline
only when a benchmark gap justifies.

---

*Reproduce: `PYTHONPATH=. .venv/bin/python -m engine.inventory`*
"""


def main() -> None:
    inv = collect()
    out = SKILL_ROOT / "INVENTORY.md"
    out.write_text(render_markdown(inv), encoding="utf-8")
    print(f"wrote {out.relative_to(SKILL_ROOT.parent.parent)}")
    print(f"  MCP tools: {inv['mcp_tools_total']}")
    print(f"  registered primitives: {inv['venous_registered_total']}")
    print(f"  staged primitives: {inv['extracted_staged_total']}  (+{inv['extracted_quarantined']} quarantined)")


if __name__ == "__main__":
    main()
