#!/usr/bin/env python3
"""Generate cross-reference.json and cross-reference.md for HuGR Arsenal.

Maps: specs <-> MCP tools <-> primitives <-> generators.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
SPECS_DIR = ROOT / "specs"
ADAPT_DIR = ROOT / "adapt"
VENOUS_DIR = ROOT / "core" / "venous"
GENERATORS_DIR = ROOT / "generators"
OUTPUT_JSON = SPECS_DIR / "cross-reference.json"
OUTPUT_MD = SPECS_DIR / "cross-reference.md"

# ---------------------------------------------------------------------------
# 1. Discover specs
# ---------------------------------------------------------------------------

def parse_spec(path: Path) -> dict:
    """Extract metadata from a spec file."""
    text = path.read_text()
    # Invariants
    invariants = re.findall(r"^(INV-[A-Z]{2,}-\d+)\s*\|", text, re.MULTILINE)
    # Tool name from filename
    m = re.match(r"TOOL-\d+-([a-z0-9_]+)\.md", path.name)
    tool_name = m.group(1) if m else None
    # Category
    category = None
    cat_m = re.search(r"Category\s*\|\s*(.+?)\s*\|", text)
    if cat_m:
        category = cat_m.group(1).strip()
    # MCP tool name
    mcp_name = None
    mcp_m = re.search(r"Tool name\s*\|\s*`([^`]+)`", text)
    if mcp_m:
        mcp_name = mcp_m.group(1).strip()
    # Spec status
    status = None
    status_m = re.search(r"\*\*Status\*\*:\s*(.+)", text)
    if status_m:
        status = status_m.group(1).strip()

    return {
        "spec_id": re.match(r"(TOOL-\d+)", path.name).group(1),
        "spec_path": f"specs/{path.name}",
        "tool_name": tool_name,
        "mcp_name": mcp_name,
        "category": category,
        "status": status,
        "invariants": sorted(set(invariants)),
    }

spec_files = sorted(SPECS_DIR.glob("TOOL-*.md"))
specs = {s["spec_id"]: s for s in (parse_spec(p) for p in spec_files)}

# ---------------------------------------------------------------------------
# 2. Discover MCP tools (adapt/)
# ---------------------------------------------------------------------------

def _extract_mcp_tool(text: str, path: Path) -> dict | None:
    """Extract MCP_TOOL dict from source text, or None."""
    if "MCP_TOOL" not in text:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MCP_TOOL":
                    try:
                        d = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
                    name = d.get("name", "")
                    entry = d.get("entry", "")
                    tool_dir = path.parent.name
                    parts = path.parent.relative_to(ROOT).parts
                    module_path = ".".join(parts)
                    return {
                        "name": name,
                        "entry": entry,
                        "tool_dir": tool_dir,
                        "module_path": module_path,
                        "primitives": d.get("imports_primitives", []),
                        "adapters": d.get("imports_adapters", []),
                        "tags": d.get("tags", []),
                        "source": str(path.parent.relative_to(ROOT)),
                    }
    return None

def discover_adapt_tools() -> dict:
    """Find all MCP_TOOL definitions in adapt/ (modules + packages)."""
    tools = {}
    # Scan all .py files in adapt/ for MCP_TOOL
    for py in ADAPT_DIR.rglob("*.py"):
        # Skip _*.py helpers but NOT __init__.py (packages)
        if py.name.startswith("_") and py.name != "__init__.py":
            continue
        # Skip test files — UNLESS they have __test__ = False (tool impl)
        if py.name.startswith("test_"):
            text_peek = py.read_text()
            if "__test__ = False" not in text_peek:
                continue
        text = py.read_text()
        result = _extract_mcp_tool(text, py)
        if result:
            tools[result["name"]] = result
    return tools

adapt_tools = discover_adapt_tools()

# ---------------------------------------------------------------------------
# 3. Discover primitives
# ---------------------------------------------------------------------------

def discover_primitives() -> dict:
    """Find all registered primitives in core/venous/<ns>/<Name>/."""
    primitives = {}
    for init in VENOUS_DIR.rglob("*/__init__.py"):
        # Must be <ns>/<Name>/__init__.py (PascalCase dir = primitive)
        parts = init.parent.relative_to(VENOUS_DIR).parts
        if len(parts) != 2:
            continue
        ns, name = parts
        # Skip staging/adapters/ports
        if ns.startswith("_"):
            continue
        # Verify it's PascalCase (primitive)
        if not name[0].isupper():
            continue
        fqn = f"core.venous.{ns}.{name}"
        primitives[fqn] = {
            "namespace": ns,
            "name": name,
            "path": fqn,
            "file": str(init.parent.relative_to(ROOT)),
        }
    return primitives

primitives = discover_primitives()

# ---------------------------------------------------------------------------
# 4. Discover generators
# ---------------------------------------------------------------------------

def discover_generators() -> dict:
    """Find generators in generators/."""
    gens = {}
    # Direct .py files in generators/ subdirs
    for py in GENERATORS_DIR.rglob("*.py"):
        if py.name.startswith("_"):
            continue
        rel = py.relative_to(GENERATORS_DIR)
        # generators/tools/add_*.py -> tool mapping
        if rel.parts[0] == "tools" and rel.name.startswith("add_"):
            tool_name = rel.stem.replace("add_", "")
            gens[tool_name] = {
                "name": tool_name,
                "path": f"generators/{rel}",
                "type": "tool_generator",
                "source": str(rel),
            }
        elif rel.parts[0] != "tools":
            # Category generator (auth, database, etc.)
            name = rel.stem
            gens[name] = {
                "name": name,
                "path": f"generators/{rel}",
                "type": "category_generator",
                "source": str(rel),
            }
    return gens

generators = discover_generators()

# ---------------------------------------------------------------------------
# 5. Build cross-reference entries
# ---------------------------------------------------------------------------

def match_tool_to_spec(spec: dict, tools: dict) -> tuple[str | None, str]:
    """Find the MCP tool matching a spec. Returns (tool_name, confidence)."""
    spec_tool = spec["tool_name"]
    if not spec_tool:
        return None, "none"

    # Exact match on tool_dir name
    for name, tool in tools.items():
        if tool["tool_dir"] == spec_tool:
            return name, "high"

    # Match on entry function name
    for name, tool in tools.items():
        if tool["entry"] == spec_tool:
            return name, "high"

    # Partial match: tool_dir contains spec_tool or vice versa
    for name, tool in tools.items():
        if spec_tool in tool["tool_dir"] or tool["tool_dir"] in spec_tool:
            return name, "medium"

    # Match by MCP name in spec
    mcp = spec.get("mcp_name")
    if mcp:
        for name, tool in tools.items():
            if mcp == name:
                return name, "high"
            if mcp.replace("fastapi_", "") in name:
                return name, "medium"

    return None, "none"

def match_primitive_to_tool(tool: dict, prims: dict) -> tuple[str | None, str]:
    """Find the primitive matched to a tool via imports_primitives."""
    imps = tool.get("primitives", [])
    if not imps:
        return None, "none"
    # Direct FQN match
    for imp in imps:
        if imp in prims:
            return imp, "high"
    # Try matching by last component
    for imp in imps:
        short = imp.split(".")[-1]
        for fqn, prim in prims.items():
            if prim["name"] == short:
                return fqn, "medium"
    return None, "low"

def match_generator_to_tool(tool: dict, gens: dict) -> tuple[str | None, str]:
    """Find the generator for a tool."""
    entry = tool.get("entry", "")
    if not entry:
        return None, "none"
    # Direct: generators/tools/add_{entry}.py
    if entry in gens and gens[entry].get("type") == "tool_generator":
        return entry, "high"
    # Suffix/prefix match with word boundary awareness
    entry_parts = set(entry.split("_"))
    for name, gen in gens.items():
        if gen.get("type") != "tool_generator":
            continue
        name_parts = set(name.split("_"))
        # Shared word components (e.g. "websocket" in "websocket_chat" and "websocket")
        if entry_parts & name_parts:
            shared = entry_parts & name_parts
            # Only confident if the shared part is a meaningful word (len > 3)
            if all(len(w) > 3 for w in shared):
                return name, "medium"
    return None, "none"

# Build all entries
entries = []
spec_ids_seen = set()
tool_names_seen = set()
primitive_fqns_seen = set()
generator_names_seen = set()

for spec_id, spec in sorted(specs.items()):
    spec_ids_seen.add(spec_id)
    tool_name, tool_conf = match_tool_to_spec(spec, adapt_tools)
    tool = adapt_tools.get(tool_name) if tool_name else None

    prim_fqn = None
    prim_conf = "none"
    gen_name = None
    gen_conf = "none"

    if tool:
        tool_names_seen.add(tool_name)
        prim_fqn, prim_conf = match_primitive_to_tool(tool, primitives)
        gen_name, gen_conf = match_generator_to_tool(tool, generators)

    if prim_fqn:
        primitive_fqns_seen.add(prim_fqn)
    if gen_name:
        generator_names_seen.add(gen_name)

    # Determine overall linkage status
    has_tool = tool is not None
    has_prim = prim_fqn is not None
    has_gen = gen_name is not None

    if has_tool and has_prim:
        linkage = "full"
    elif has_tool:
        linkage = "partial"
    else:
        linkage = "spec_only"

    entry = {
        "spec_id": spec_id,
        "spec_path": spec["spec_path"],
        "tool_name": spec["tool_name"],
        "tool_module": tool["source"] if tool else None,
        "mcp_tool_name": tool["name"] if tool else None,
        "primitive": {
            "namespace": primitives[prim_fqn]["namespace"],
            "name": primitives[prim_fqn]["name"],
            "path": prim_fqn,
        } if prim_fqn else None,
        "generator": generators[gen_name]["path"] if gen_name else None,
        "tags": tool.get("tags", []) if tool else [],
        "invariants": spec["invariants"],
        "linkage": linkage,
        "confidence": {
            "tool": tool_conf,
            "primitive": prim_conf,
            "generator": gen_conf,
        },
    }
    entries.append(entry)

# Orphan tools (tools with no matching spec)
for tool_name, tool in sorted(adapt_tools.items()):
    if tool_name not in tool_names_seen:
        prim_fqn, prim_conf = match_primitive_to_tool(tool, primitives)
        gen_name, gen_conf = match_generator_to_tool(tool, generators)
        if prim_fqn:
            primitive_fqns_seen.add(prim_fqn)
        if gen_name:
            generator_names_seen.add(gen_name)
        entries.append({
            "spec_id": None,
            "spec_path": None,
            "tool_name": tool["entry"],
            "tool_module": tool["source"],
            "mcp_tool_name": tool_name,
            "primitive": {
                "namespace": primitives[prim_fqn]["namespace"],
                "name": primitives[prim_fqn]["name"],
                "path": prim_fqn,
            } if prim_fqn else None,
            "generator": generators[gen_name]["path"] if gen_name else None,
            "tags": tool.get("tags", []),
            "invariants": [],
            "linkage": "tool_only",
            "confidence": {
                "tool": "high",
                "primitive": prim_conf,
                "generator": gen_conf,
            },
        })

# Orphan primitives (no tool references them)
for fqn, prim in sorted(primitives.items()):
    if fqn not in primitive_fqns_seen:
        entries.append({
            "spec_id": None,
            "spec_path": None,
            "tool_name": None,
            "tool_module": None,
            "mcp_tool_name": None,
            "primitive": {
                "namespace": prim["namespace"],
                "name": prim["name"],
                "path": fqn,
            },
            "generator": None,
            "tags": [],
            "invariants": [],
            "linkage": "primitive_only",
            "confidence": {
                "tool": "none",
                "primitive": "high",
                "generator": "none",
            },
        })

# Orphan generators (no tool maps to them)
for name, gen in sorted(generators.items()):
    if name not in generator_names_seen:
        entries.append({
            "spec_id": None,
            "spec_path": None,
            "tool_name": None,
            "tool_module": None,
            "mcp_tool_name": None,
            "primitive": None,
            "generator": gen["path"],
            "tags": [],
            "invariants": [],
            "linkage": "generator_only",
            "confidence": {
                "tool": "none",
                "primitive": "none",
                "generator": "high",
            },
        })

# ---------------------------------------------------------------------------
# 6. Write JSON
# ---------------------------------------------------------------------------

now = datetime.now(timezone.utc).isoformat()
cross_ref = {
    "generated": now,
    "version": "1.0.0",
    "summary": {
        "total_entries": len(entries),
        "specs_total": len(specs),
        "tools_total": len(adapt_tools),
        "primitives_total": len(primitives),
        "generators_total": len(generators),
        "full_linkage": sum(1 for e in entries if e["linkage"] == "full"),
        "partial_linkage": sum(1 for e in entries if e["linkage"] == "partial"),
        "spec_only": sum(1 for e in entries if e["linkage"] == "spec_only"),
        "tool_only": sum(1 for e in entries if e["linkage"] == "tool_only"),
        "primitive_only": sum(1 for e in entries if e["linkage"] == "primitive_only"),
        "generator_only": sum(1 for e in entries if e["linkage"] == "generator_only"),
        "confidence_distribution": {
            "high": sum(1 for e in entries if e["confidence"]["tool"] == "high"),
            "medium": sum(1 for e in entries if e["confidence"]["tool"] == "medium"),
            "low": sum(1 for e in entries if e["confidence"]["tool"] == "low"),
            "none": sum(1 for e in entries if e["confidence"]["tool"] == "none"),
        },
    },
    "entries": entries,
}

OUTPUT_JSON.write_text(json.dumps(cross_ref, indent=2) + "\n")
print(f"Wrote {OUTPUT_JSON}")

# ---------------------------------------------------------------------------
# 7. Write Markdown
# ---------------------------------------------------------------------------

lines = [
    "# HuGR Arsenal — Cross-Reference Index",
    "",
    f"**Generated**: {now}",
    f"**Version**: 1.0.0",
    "",
    "## Summary",
    "",
    f"| Metric | Count |",
    f"|--------|------:|",
    f"| Total entries | {len(entries)} |",
    f"| Specs (TOOL-NNN-*.md) | {len(specs)} |",
    f"| MCP tools | {len(adapt_tools)} |",
    f"| Registered primitives | {len(primitives)} |",
    f"| Generators | {len(generators)} |",
    f"| **Full linkage** (spec+tool+primitive) | {cross_ref['summary']['full_linkage']} |",
    f"| Partial linkage (spec+tool) | {cross_ref['summary']['partial_linkage']} |",
    f"| Spec only (no tool found) | {cross_ref['summary']['spec_only']} |",
    f"| Tool only (no spec) | {cross_ref['summary']['tool_only']} |",
    f"| Primitive only (no tool/spec) | {cross_ref['summary']['primitive_only']} |",
    f"| Generator only (no tool/spec) | {cross_ref['summary']['generator_only']} |",
    "",
    "## Full Index",
    "",
    "| Spec | Tool | Primitive | Generator | Linkage | Confidence |",
    "|------|------|-----------|-----------|---------|------------|",
]

for e in entries:
    spec = e["spec_id"] or "—"
    tool = e["tool_name"] or "—"
    if e["mcp_tool_name"]:
        tool = f"`{e['mcp_tool_name']}`"
    prim = "—"
    if e["primitive"]:
        prim = f"`{e['primitive']['namespace']}/{e['primitive']['name']}`"
    gen = e["generator"] or "—"
    linkage = e["linkage"]
    conf = e["confidence"]["tool"]
    if linkage == "full":
        status = "✅ Full"
    elif linkage == "partial":
        status = "⚠️ Partial"
    elif linkage == "spec_only":
        status = "📄 Spec"
    elif linkage == "tool_only":
        status = "🔧 Tool"
    elif linkage == "primitive_only":
        status = "⚙️ Primitive"
    else:
        status = "📦 Gen"
    lines.append(f"| {spec} | {tool} | {prim} | {gen} | {status} | {conf} |")

lines.extend([
    "",
    "## Confidence Legend",
    "",
    "- **high** — direct match (name/FQN/exact import)",
    "- **medium** — heuristic/partial name overlap",
    "- **low** — uncertain mapping",
    "- **none** — no match found",
    "",
    "## Linkage Types",
    "",
    "- ✅ **Full** — spec + tool + primitive mapped",
    "- ⚠️ **Partial** — spec + tool (no primitive)",
    "- 📄 **Spec only** — spec exists, no matching tool found",
    "- 🔧 **Tool only** — tool exists, no matching spec",
    "- ⚙️ **Primitive only** — primitive not referenced by any tool",
    "- 📦 **Generator only** — generator not mapped to any tool",
])

OUTPUT_MD.write_text("\n".join(lines) + "\n")
print(f"Wrote {OUTPUT_MD}")

# ---------------------------------------------------------------------------
# 8. Report
# ---------------------------------------------------------------------------

s = cross_ref["summary"]
print(f"""
╔══════════════════════════════════════════════════════════════╗
║  CROSS-REFERENCE GENERATED                                  ║
╠══════════════════════════════════════════════════════════════╣
║  Total entries:          {s['total_entries']:>5}                         ║
║  Full linkage:           {s['full_linkage']:>5}  (spec+tool+primitive)     ║
║  Partial linkage:        {s['partial_linkage']:>5}  (spec+tool)                ║
║  Spec only (orphans):    {s['spec_only']:>5}                         ║
║  Tool only (orphans):    {s['tool_only']:>5}                         ║
║  Primitive orphans:      {s['primitive_only']:>5}                         ║
║  Generator orphans:      {s['generator_only']:>5}                         ║
╠══════════════════════════════════════════════════════════════╣
║  Confidence: high={s['confidence_distribution']['high']}  medium={s['confidence_distribution']['medium']}  low={s['confidence_distribution']['low']}  none={s['confidence_distribution']['none']}      ║
╚══════════════════════════════════════════════════════════════╝
""")
