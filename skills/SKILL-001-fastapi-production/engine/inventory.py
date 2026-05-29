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
        and not any(
            pt.startswith(("_quarantine", "__pycache__")) for pt in p.relative_to(root).parts[:-1]
        )
    )


def _count_mcp_tools() -> int:
    n = 0
    for py in SKILL_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or "_staging" in py.parts:
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


def _count_primitive_dirs(
    root: Path, exclude: set[str] | None = None, *, pascal_only: bool = False
) -> int:
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
        if pascal_only and not (p.name[:1].isupper() and "_" not in p.name):
            continue
        # A "primitive dir" has a <Name>.py matching its directory name
        if (p / f"{p.name}.py").exists():
            n += 1
    return n


def collect() -> dict:
    root = SKILL_ROOT

    # adapt/ breakdown
    adapt_subdirs = ["extend", "verify", "operate", "evolve", "proactive", "contracts"]
    adapt: dict[str, int] = {}
    for sub in adapt_subdirs:
        adapt[sub] = _count_py(root / "adapt" / sub)

    # adapt/extend/ subdomains
    extend_subdomains: dict[str, int] = {}
    ext_root = root / "adapt" / "extend"
    if ext_root.exists():
        for p in sorted(ext_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                extend_subdomains[p.name] = _count_py(p)

    # generators/
    generators: dict[str, int] = {}
    gen_root = root / "generators"
    if gen_root.exists():
        for p in sorted(gen_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                generators[p.name] = _count_py(p)

    # modules/
    modules: dict[str, int] = {}
    mod_root = root / "modules"
    if mod_root.exists():
        for p in sorted(mod_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                modules[p.name] = _count_py(p)

    # core/venous — registered primitives per namespace (excluding _staging, _adapters)
    venous_ns: dict[str, int] = {}
    venous_root = root / "core" / "venous"
    if venous_root.exists():
        for p in sorted(venous_root.iterdir()):
            if p.is_dir() and not p.name.startswith(("_", ".")):
                venous_ns[p.name] = _count_primitive_dirs(p)

    # Adapters
    adapter_count = 0
    adapt_root = root / "core" / "venous" / "_adapters" / "fastapi"
    if adapt_root.exists():
        adapter_count = sum(
            1 for p in adapt_root.glob("*.py") if not p.name.startswith(("_", "test_"))
        )

    # _staging staged — count only valid PascalCase dirs (the subset that
    # makes it into the catalog as `status="staged"`).
    extracted_ns: dict[str, int] = {}
    ext_staged = root / "core" / "venous" / "_staging"
    if ext_staged.exists():
        for p in sorted(ext_staged.iterdir()):
            if p.is_dir():
                pascal_only = p.name != "_quarantine"
                extracted_ns[p.name] = _count_primitive_dirs(p, pascal_only=pascal_only)

    # catalog.json — schema v2 (ADR-0003): hierarchical skill × bundle ×
    # tool surface. The `counts` block now carries `tools_total`,
    # `tools_local`, `tools_federated`, `primitives`, `recipes`,
    # `skills`, and `bundles`. The headline + the new §2 section below
    # render from this dict; B0.5/B4.7 audit the resulting INVENTORY.md
    # against catalog.json's own counts.
    catalog_path = root / "engine" / "index" / "catalog.json"
    catalog_counts = {
        "tools_total": 0,
        "tools_local": 0,
        "tools_federated": 0,
        "primitives": 0,
        "recipes": 0,
        "skills": 0,
        "bundles": 0,
    }
    catalog_skills: list[dict] = []
    if catalog_path.exists():
        try:
            cat = json.loads(catalog_path.read_text())
            cat_counts = cat.get("counts") or {}
            for k in catalog_counts:
                if k in cat_counts:
                    catalog_counts[k] = int(cat_counts[k])
            # Fall back from array lengths when counts.* are missing
            # (a half-migrated catalog wouldn't pass B2.8 anyway, but
            # the inventory should still render).
            if not catalog_counts["tools_total"]:
                catalog_counts["tools_total"] = len(cat.get("tools", []))
            if not catalog_counts["primitives"]:
                catalog_counts["primitives"] = len(cat.get("primitives", []))
            if not catalog_counts["recipes"]:
                catalog_counts["recipes"] = len(cat.get("recipes", []))
            catalog_skills = list(cat.get("skills", []))
            if not catalog_counts["skills"]:
                catalog_counts["skills"] = len(catalog_skills)
            if not catalog_counts["bundles"]:
                catalog_counts["bundles"] = sum(len(s.get("bundles", [])) for s in catalog_skills)
        except (OSError, json.JSONDecodeError):
            pass

    # Examples + specs
    # Count only populated example directories — empty scaffolds don't count.
    def _has_files(d: Path) -> bool:
        return any(f.is_file() for f in d.rglob("*") if ".pycache" not in f.parts)

    # Examples live at repo root (canonical location, per CONTRACT §B4.2),
    # not inside the skill tree. We resolve to `<repo_root>/examples/`.
    examples_dir = root.parent.parent / "examples"
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
    specs = sum(
        1 for p in (root / "specs").glob("*.md") if not p.name.startswith(("README", "RESUME"))
    )
    benchmark_specs = (
        sum(
            1
            for p in (root / "benchmarks" / "specs").rglob("*.md")
            if p.name.upper() != "README.MD"
        )
        if (root / "benchmarks" / "specs").exists()
        else 0
    )

    return {
        "mcp_tools_total": _count_mcp_tools(),
        "catalog": catalog_counts,
        "catalog_skills": catalog_skills,
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

    cat = inv["catalog"]
    skills_count = cat["skills"]
    bundles_count = cat["bundles"]
    tools_total = cat["tools_total"]
    tools_local = cat["tools_local"]
    tools_federated = cat["tools_federated"]
    skill_word = "skill" if skills_count == 1 else "skills"
    bundle_word = "bundle" if bundles_count == 1 else "bundles"

    # Schema v2 (ADR-0003): the §2 Skills × Bundles section enumerates
    # each skill's bundles + per-bundle tool counts + bundle tags. The
    # headline mirrors the same hierarchy so B0.5 + B4.7 can cross-check
    # against catalog.json's `counts` block.
    skill_section_lines: list[str] = []
    for s in inv.get("catalog_skills", []):
        sname = s.get("name", "")
        sver = s.get("version", "")
        stype = s.get("type", "local")
        skill_section_lines.append(f"### `{sname}` — v{sver} ({stype})")
        skill_section_lines.append("")
        skill_section_lines.append("| bundle | tools | tags |")
        skill_section_lines.append("|---|---:|---|")
        for b in s.get("bundles", []):
            bname = b.get("name", "")
            bcount = b.get("tool_count", 0)
            btags = ", ".join(b.get("tags", []))
            skill_section_lines.append(f"| `{bname}` | {bcount} | {btags} |")
        skill_section_lines.append("")
    skill_section = "\n".join(skill_section_lines).rstrip() or "_(no skills registered)_"

    return f"""# SKILL-001 Inventory — Machine-Verified

> Generated by `python -m engine.inventory`. Every claim in CLAUDE.md,
> STATUS.md, SKILL.md, memory, ROADMAP must reconcile against this file.
> Drift = audit bug.

## Headline

- **{inv["mcp_tools_total"]} files carry `MCP_TOOL` metadata** (agent-visible surface).
- **Catalog:** {skills_count} {skill_word}, {bundles_count} {bundle_word}, {tools_total} tools ({tools_local} local + {tools_federated} federated), {cat["primitives"]} primitives, {cat["recipes"]} recipes.
- **{inv["venous_registered_total"]} registered primitives** (`core/venous/<ns>/<Name>/`).
- **{inv["extracted_staged_total"]} staged primitives** in `_staging/` (plus {inv["extracted_quarantined"]} quarantined).
- **{inv["adapters_fastapi"]} FastAPI adapters** (production-wired).
- **{inv["modules_total"]} `modules/` packages** (pre-built feature bundles).
- **{inv["examples"]} populated examples** ({inv["examples_empty"]} empty scaffolds), {inv["specs"]} specs, {inv["benchmark_specs"]} benchmark specs.

---

## 1. adapt/ — {inv["adapt_total"]} tools

{_table(inv["adapt"], "bucket")}

### adapt/extend/ sub-domains ({sum(inv["extend_subdomains"].values())} tools)

{_table(inv["extend_subdomains"], "domain")}

## 2. Skills × Bundles

Hierarchical surface (catalog schema v2 / ADR-0003). Each tool ships
under exactly one skill + one bundle; the tier-1 router uses this map
to expose ~80-tool bundle slices via `fastapi_meta_list_bundle` /
`fastapi_meta_activate_bundle` instead of flooding `tools/list` with
the full surface.

{skill_section}

## 3. generators/ — {inv["generators_total"]} tools

{_table(inv["generators"], "category")}

## 4. modules/ — {inv["modules_total"]} modules

{_table(inv["modules"], "module")}

## 5. core/venous — registered primitives ({inv["venous_registered_total"]})

{_table(inv["venous_registered"], "namespace")}

Plus **{inv["adapters_fastapi"]} FastAPI adapters** under `core/venous/_adapters/fastapi/`.

## 6. core/venous/_staging — staged primitives ({inv["extracted_staged_total"]} + {inv["extracted_quarantined"]} quarantined)

{_table(inv["extracted_staged"], "namespace")}

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
    print(
        f"  staged primitives: {inv['extracted_staged_total']}  (+{inv['extracted_quarantined']} quarantined)"
    )


if __name__ == "__main__":
    main()
