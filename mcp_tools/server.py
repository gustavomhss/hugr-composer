"""FastMCP application instance with SKILL-001 instructions.

Server instructions are DERIVED from the registered tier-1 tool metadata
(``mcp_tools.tier1``) and the kit catalog (``engine/index/catalog.json``)
so the advertised surface cannot drift from the actual surface — Codex 3
F-012 closed the prior hand-maintained list that pointed at retired
tools (``fastapi_generate_project`` / ``fastapi_analyze``) and stale
audit counts.

Falling back to a minimal static string is intentional: if the catalog
or tier1 module is unavailable at import time (e.g. partial install),
the server must still boot — but the advertised tool list is honest:
"call fastapi_meta_home" is always safe because it self-describes.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_tools.auth_gate import HugrTokenVerifier, gate_enabled

# Subscription gate: when HUGR_GATE is enabled the server requires a valid HuGR
# license (bearer token) to expose any tool. Off by default → local stdio / OSS
# / test flows are unchanged. See mcp_tools/auth_gate.py.
_auth = HugrTokenVerifier() if gate_enabled() else None


def _build_instructions() -> str:
    """Compose the server instructions from registered tier-1 metadata.

    Pulls the eight ``MCP_TOOL*`` dicts from ``mcp_tools.tier1`` and the
    headline counts from ``engine/index/catalog.json``. Failure to read
    either source falls back to a minimal honest pointer at
    ``fastapi_meta_home`` — never invents tool names or counts.
    """
    # Default fallback — always honest, always callable.
    fallback = (
        "FastAPI Production skill — production-grade scaffolding + "
        "adaptation of existing FastAPI projects.\n\n"
        "ENTRY: Call `fastapi_meta_home` first — it returns the live "
        "landscape (skills, bundles, primitives, recipes) drawn from "
        "the catalog. From there, narrow with `fastapi_meta_search` or "
        "scaffold with `fastapi_meta_scaffold`.\n\n"
        "All tier-1 tools self-describe; the catalog is the source of "
        "truth for tool counts and names."
    )

    # Try to derive from the live tier-1 surface + catalog.
    try:
        import json
        from pathlib import Path

        from mcp_tools import tier1 as _tier1

        skill_root = Path(_tier1.__file__).resolve().parents[1]
        catalog_path = skill_root / "engine" / "index" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        counts = catalog.get("counts", {})
        tools_total = int(counts.get("tools_total", counts.get("tools", 0)))
        primitives_total = int(counts.get("primitives", 0))
        recipes_total = int(counts.get("recipes", 0))

        # Walk every module-level MCP_TOOL* dict in tier1 — discovery uses
        # exactly this set (audit rule B2.7 enforces count = 8).
        tier1_tools: list[tuple[str, str]] = []
        for attr in dir(_tier1):
            if not attr.startswith("MCP_TOOL"):
                continue
            val = getattr(_tier1, attr)
            if not isinstance(val, dict):
                continue
            name = val.get("name")
            if not isinstance(name, str):
                continue
            desc = val.get("description", "")
            # First sentence only — keep instructions compact (cognition
            # cap < ~1500 tokens for the static instructions block).
            first_sentence = desc.split(". ", 1)[0].strip().rstrip(".") + "."
            tier1_tools.append((name, first_sentence))
        tier1_tools.sort(key=lambda x: x[0])

        if not tier1_tools or tools_total <= 0:
            return fallback

        lines = [
            "FastAPI Production skill — generates SOTA production "
            "projects AND adapts existing ones.",
            "",
            "Convention over Configuration: generators deliver calibrated "
            "defaults (argon2id, async pools, security headers, "
            "multi-stage Docker); you customize business logic only.",
            "",
            (
                f"Catalog (machine-verified): {tools_total} tools, "
                f"{primitives_total} primitives, {recipes_total} recipes."
            ),
            "",
            (
                "ENTRY: call `fastapi_meta_home` first. The eight tier-1 "
                "meta tools below are always loaded; everything else is "
                "reachable via meta_search / meta_describe / "
                "meta_activate_bundle."
            ),
            "",
            "TIER-1 TOOLS:",
        ]
        for name, blurb in tier1_tools:
            lines.append(f"  - {name}: {blurb}")
        lines.append("")
        lines.append(
            "Auth/verify tools are SKILL-KIT scoped (cwd = SKILL_ROOT). "
            "For emitted-project validation, run `pytest` inside the "
            "scaffold."
        )
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 — server boot must not fail on instruction build
        return fallback


mcp = FastMCP(
    "hugr-skill-fastapi",
    auth=_auth,
    instructions=_build_instructions(),
)
