"""Phase 2 tier-1 surface — mcp_tools/tier1.py runtime audit (CONTRACT.md §B2.6 + §B2.7).

CONTRACT.md scope: §B2.6 tier-1 runtime strings match catalog +
scope-disclaim; §B2.7 tier-1 surface inventory (exactly 8 MCP_TOOL*
dicts at module top of ``mcp_tools/tier1.py``).

Separate from ``phase2_catalog`` because both B2.6 and B2.7 parse
``mcp_tools/tier1.py`` (runtime-string truth check + AST surface
inventory), use a different family of regexes (``MCP_TOOL_*`` dict
literals + workflow lists), and share no helper with the rest of B2
except ``_common``. Splitting B2 into catalog + skill_md + tier1 keeps
every module ≤500 LOC and respects the three distinct surfaces B2 rules
audit (catalog file, agent entry doc, tier-1 runtime tool surface).
"""

from __future__ import annotations

import json
import re

from ._common import SKILL_ROOT


def _r_tier1_surface_truth() -> tuple[bool, str]:
    """B2.6 — tier-1 runtime strings tell the truth about the catalog.

    The tier-1 meta tools (mcp_tools/tier1.py) ship three agent-visible
    runtime surfaces: the module docstring, each MCP_TOOL description,
    and the workflow breadcrumb list inside `fastapi_meta_home()`'s
    return envelope. Prior audits read SKILL.md (the prose contract)
    but never diffed these literal runtime strings against the catalog
    they describe. Codex v6 + Opus sign-off both caught the residual
    drift: tier1.py kept advertising the pre-freeze `180 tools` / `122
    primitives` counts long after catalog.json moved to 201 / 299, and
    Wave F B2's SKILL.md skill-kit-vs-emitted-project split never
    propagated to the `fastapi_meta_home` workflow steps.

    This rule fails CI on:
      - any mention of a pre-freeze stale count (`180 tool(s|-tool)`,
        `122 primitive(s)`) anywhere in tier1.py
      - missing qualifier text in `fastapi_meta_audit` /
        `fastapi_meta_verify` descriptions: both MUST state the tool
        operates on the skill kit itself (not an emitted project)
      - missing current canonical count: tier1.py MUST cite the live
        catalog tool count somewhere (we search for `N tool`/`N-tool`
        where N = catalog.counts.tools) so a subsequent count bump
        forces this file to be updated deliberately.
    """
    tier1 = SKILL_ROOT / "mcp_tools" / "tier1.py"
    if not tier1.exists():
        return False, "missing: mcp_tools/tier1.py"
    src = tier1.read_text(encoding="utf-8")

    # Canonical counts from catalog.json (the machine source).
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog_path.exists():
        return False, "missing: engine/index/catalog.json"
    try:
        cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json malformed: {exc}"
    # Schema v2: `tools_total` replaces v1 flat `tools` key (ADR-0003).
    # Falls back to legacy `tools` only if a transitional catalog ever
    # ships; today catalog.json always emits `tools_total`.
    _counts = cat.get("counts", {})
    tool_count = int(_counts.get("tools_total", _counts.get("tools", 0)))
    primitive_count = int(_counts.get("primitives", 0))
    if tool_count <= 0 or primitive_count <= 0:
        return False, (
            "catalog.json counts.tools_total / counts.primitives missing "
            "or zero — cannot validate tier1 surface truth"
        )

    # Stale-count detector — SCOPED to agent-visible runtime strings
    # only. Matches on:
    #   - `"description": ( ... )` blocks inside MCP_TOOL* dicts
    #   - the `"workflow": [ ... ]` list inside fastapi_meta_home's
    #     return envelope (the strings the agent reads at runtime)
    # Module docstrings, comments, and research citations like
    # "30–50-tool degradation threshold" are deliberately excluded —
    # they are internal commentary, not runtime surface.
    agent_visible_blobs: list[str] = []
    for m in re.finditer(
        r'"description":\s*\(\s*((?:[^()]|\([^)]*\))*?)\s*\),',
        src,
        re.DOTALL,
    ):
        agent_visible_blobs.append(m.group(1))
    wf_match = re.search(
        r'"workflow":\s*\[(.*?)\],',
        src,
        re.DOTALL,
    )
    if wf_match:
        agent_visible_blobs.append(wf_match.group(1))
    scoped_src = "\n".join(agent_visible_blobs)
    if not scoped_src:
        return False, (
            "could not extract MCP_TOOL descriptions + workflow from "
            "mcp_tools/tier1.py — file shape changed?"
        )

    tool_claims = set(int(m) for m in re.findall(r"\b(\d+)[\s-]+tool(?:s|-catalog)?\b", scoped_src))
    primitive_claims = set(int(m) for m in re.findall(r"\b(\d+)\s+primitive(?:s)?\b", scoped_src))
    # Any claim in agent-visible text that isn't the canonical count
    # AND isn't a small structural literal (≤20) is stale.
    stale_tool_claims = sorted(n for n in tool_claims if n != tool_count and n > 20)
    stale_primitive_claims = sorted(n for n in primitive_claims if n != primitive_count and n > 20)
    if stale_tool_claims:
        return False, (
            f"mcp_tools/tier1.py agent-visible text carries stale "
            f"tool-count claims {stale_tool_claims} — current catalog "
            f"has {tool_count} tools. Update the MCP_TOOL descriptions "
            f"+ workflow strings."
        )
    if stale_primitive_claims:
        return False, (
            f"mcp_tools/tier1.py agent-visible text carries stale "
            f"primitive-count claims {stale_primitive_claims} — current "
            f"registry has {primitive_count} primitives."
        )
    if tool_count not in tool_claims:
        return False, (
            f"mcp_tools/tier1.py MCP_TOOL descriptions + workflow do "
            f"not cite the current catalog tool count ({tool_count}) "
            f"anywhere. The agent reads these strings; they must "
            f"advertise the real surface size."
        )

    # Skill-kit scope qualifier — _audit and _verify MUST say what they
    # operate on (Wave F B2 lesson: agents took "audit" to mean
    # emitted-project validation; both descriptions must now disclaim).
    audit_match = re.search(
        r"MCP_TOOL_AUDIT\s*=\s*\{.*?\}",
        src,
        re.DOTALL,
    )
    verify_match = re.search(
        r"MCP_TOOL_VERIFY\s*=\s*\{.*?\}",
        src,
        re.DOTALL,
    )
    if not audit_match or not verify_match:
        return False, (
            "mcp_tools/tier1.py missing MCP_TOOL_AUDIT / MCP_TOOL_VERIFY "
            "block — expected at module level"
        )
    for label, block in (
        ("MCP_TOOL_AUDIT", audit_match.group(0)),
        ("MCP_TOOL_VERIFY", verify_match.group(0)),
    ):
        blob = block.lower()
        has_scope_note = (
            "skill-kit" in blob
            or "skill_root" in blob
            or "not an emitted project" in blob
            or "not the emitted project" in blob
            or "not validate an emitted project" in blob
        )
        if not has_scope_note:
            return False, (
                f"{label} description missing skill-kit-vs-emitted-"
                f"project scope note. Wave F B2 requires both meta "
                f"audit tools to disclaim: they operate on the skill "
                f"kit itself, NOT an emitted project."
            )

    return True, (
        f"tier1 runtime strings cite current catalog ({tool_count} "
        f"tools, {primitive_count} primitives) + scope-disclaim audit/"
        f"verify"
    )


def _r_tier1_surface_inventory() -> tuple[bool, str]:
    """B2.7 — `mcp_tools/tier1.py` exposes exactly 8 distinct MCP_TOOL* dicts.

    The cognition cap (≤ 8 always-loaded tools) is load-bearing — once
    the surface grows past 8, the Maestro starts ignoring the descriptions
    (Anthropic 30-50-tool degradation finding) and tier-1 stops being
    "always-discoverable". This rule freezes the count at 8 after
    WAVE-0-F2 (the two bundle tools landed; the redundant MCP_TOOL_HOME
    alias was retired). Counts DISTINCT dicts (by id) so aliases don't
    inflate the surface.

    The compose tool in `mcp_tools/compose.py` is registered alongside
    tier-1 but lives in a separate module by design; this rule only
    polices the module that the dual-index design names as the tier-1
    surface (per ADR-0003).
    """
    tier1 = SKILL_ROOT / "mcp_tools" / "tier1.py"
    if not tier1.exists():
        return False, "missing: mcp_tools/tier1.py"
    # Parse module-level MCP_TOOL* assignments via AST (no import — keeps
    # this rule cheap and side-effect free, the same pattern manifest.py
    # uses to scan tool files).
    import ast as _ast

    try:
        tree = _ast.parse(tier1.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return False, f"mcp_tools/tier1.py syntax error: {exc}"

    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, _ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, _ast.Name) and target.id.startswith("MCP_TOOL")):
                continue
            # Accept literal dict OR a Name (alias). We count alias *names*
            # separately so the previous MCP_TOOL_HOME = MCP_TOOL pattern
            # would be visible to the rule; modern tier1.py should NOT use
            # such aliases — each MCP_TOOL* identifier must bind a fresh
            # dict literal. We enforce that below.
            if isinstance(node.value, _ast.Dict):
                found.add(target.id)
            elif isinstance(node.value, _ast.Name):
                return False, (
                    f"mcp_tools/tier1.py: {target.id} is an alias of "
                    f"{node.value.id} — aliases inflate the tier-1 surface "
                    "count without adding a distinct behaviour. Bind a "
                    "literal dict or remove the alias."
                )
    expected = {
        "MCP_TOOL",
        "MCP_TOOL_SEARCH",
        "MCP_TOOL_DESCRIBE",
        "MCP_TOOL_SCAFFOLD",
        "MCP_TOOL_AUDIT",
        "MCP_TOOL_VERIFY",
        "MCP_TOOL_LIST_BUNDLE",
        "MCP_TOOL_ACTIVATE_BUNDLE",
    }
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        return False, (
            f"mcp_tools/tier1.py MCP_TOOL* set mismatch: "
            f"missing={missing} extra={extra}. The cognition cap (≤ 8) "
            "freezes the tier-1 surface at exactly these eight."
        )
    if len(found) != 8:
        return False, (
            f"mcp_tools/tier1.py declares {len(found)} MCP_TOOL* dicts; "
            "the cognition cap freezes tier-1 at exactly 8."
        )
    return True, "tier-1 surface = 8 MCP_TOOL* dicts in mcp_tools/tier1.py"
