"""Auto-discover and register MCP tools from adapt/, generators/, and related dirs.

Convention: any Python module containing a top-level ``MCP_TOOL`` dict
gets registered as an MCP tool.  The dict must have:

  - name: str           -- MCP tool name (e.g. "fastapi_add_websocket_chat")
  - description: str    -- one-line summary
  - tags: list[str]     -- category tags
  - entry: str          -- function name in the module (default: module filename stem)
  - annotations: dict   -- (optional) FastMCP annotations (readOnlyHint, etc.)

Two registration paths exist:

- ``discover_and_register`` scans ``adapt/**/*.py`` and also calls
  ``register_generators_from_metadata``. Adapt tools are wrapped to
  translate ``(project_dir, dry_run)`` into ``ToolInput``.
- ``register_generators_from_metadata`` scans ``generators/**/*.py`` and
  a whitelist of sibling module dirs (``benchmark/``, ``modules/**/tools/``,
  ``core/tools/``). Entry functions are passed directly to
  ``mcp_app.tool()`` — FastMCP introspects their signatures natively.

Replaces the prior 691-line hand-coded generator registry. See
CONTRACT.md §B1.5.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
SKILL_ROOT = Path(__file__).resolve().parent.parent


def discover_and_register(mcp_app) -> int:
    """Scan adapt/ subdirectories for modules with MCP_TOOL metadata
    and register them.  Also registers generator tools via
    ``register_generators_from_metadata``.

    Returns:
        Number of tools registered.
    """
    count = 0

    adapt_dirs = [
        SKILL_ROOT / "adapt" / "extend",
        SKILL_ROOT / "adapt" / "verify",
        SKILL_ROOT / "adapt" / "operate",
        SKILL_ROOT / "adapt" / "evolve",
        SKILL_ROOT / "adapt" / "proactive",
    ]

    for base_dir in adapt_dirs:
        if not base_dir.exists():
            continue
        for py_file in sorted(base_dir.rglob("*.py")):
            if py_file.name.startswith("__"):
                continue
            if py_file.name.startswith("test_") and py_file.name != "test_coverage_gaps.py":
                continue

            module_path = _file_to_module(py_file)
            try:
                mod = importlib.import_module(module_path)
            except Exception as exc:
                logger.debug("skip %s: %s", module_path, exc)
                continue

            mcp_meta = getattr(mod, "MCP_TOOL", None)
            if mcp_meta is None:
                continue

            entry_name = mcp_meta.get("entry", py_file.stem)
            entry_fn = getattr(mod, entry_name, None)
            if not callable(entry_fn):
                logger.warning(
                    "MCP_TOOL in %s has entry=%r but function not found",
                    module_path,
                    entry_name,
                )
                continue

            _register_adapt_tool(mcp_app, mcp_meta, entry_fn)
            count += 1
            logger.debug("registered adapt tool: %s", mcp_meta["name"])

    from mcp_tools.generators import register_generators

    count += register_generators(mcp_app)
    count += register_discovery_tools(mcp_app)
    count += register_tier1_tools(mcp_app)

    logger.info("registered %d MCP tools total", count)
    return count


def register_tier1_tools(mcp_app) -> int:
    """Register the 6 tier-1 meta tools (Phase 6 dual-index design).

    Always-loaded; primacy position. See `mcp_tools/tier1.py` +
    `/docs/research/DUAL_INDEX_DESIGN.md` §4.1.
    """
    from mcp_tools.tier1 import (
        fastapi_meta_search_home,
        fastapi_meta_search_search,
        fastapi_meta_search_describe,
        fastapi_meta_generate_scaffold,
        fastapi_meta_check_audit,
        fastapi_meta_verify_verify,
        MCP_TOOL_HOME, MCP_TOOL_SEARCH, MCP_TOOL_DESCRIBE,
        MCP_TOOL_SCAFFOLD, MCP_TOOL_AUDIT, MCP_TOOL_VERIFY,
    )
    for fn, meta in (
        (fastapi_meta_search_home,     MCP_TOOL_HOME),
        (fastapi_meta_search_search,   MCP_TOOL_SEARCH),
        (fastapi_meta_search_describe, MCP_TOOL_DESCRIBE),
        (fastapi_meta_generate_scaffold, MCP_TOOL_SCAFFOLD),
        (fastapi_meta_check_audit,     MCP_TOOL_AUDIT),
        (fastapi_meta_verify_verify,   MCP_TOOL_VERIFY),
    ):
        mcp_app.tool(
            name=meta["name"],
            tags=set(meta.get("tags", [])),
        )(fn)
    return 6


def register_discovery_tools(mcp_app) -> int:
    """Register Phase 2 discoverability tools (CONTRACT §B2.1, §B2.2).

    Exposes `find_primitive(concern, query, limit)` as a first-class MCP
    tool so the Maestro can query the primitive catalog at composition
    time. Pure retrieval — no LLM call inside the tool.
    """
    from engine.discovery import find_primitive as _find
    from engine.discovery import suggest_composition as _suggest

    def find_primitive(concern: str = "", query: str = "", limit: int = 10) -> list[dict]:
        """Search the primitive catalog by concern and free-text query.

        Args:
            concern: registry concern tag (e.g. ``auth``, ``resiliency``,
                ``events``, ``observability``). Empty string searches across
                all concerns.
            query: natural-language fragment matched via BM25 over primitive
                name + purpose + compose-with + body. Example:
                ``"dedupe webhook deliveries"``.
            limit: maximum hits to return (1-10, capped at 10).

        Returns:
            List of ``{name, namespace, concern, purpose, score}`` dicts
            ranked by BM25 relevance descending.
        """
        return _find(concern=concern, query=query, limit=limit)

    mcp_app.tool(
        name="fastapi_find_primitive",
        tags={"discovery", "catalog", "retrieval"},
    )(find_primitive)

    def suggest_composition(intent: str, limit: int = 5) -> list[dict]:
        """Rank compose-with recipes against a free-text intent.

        Args:
            intent: natural-language description of what to build — e.g.
                ``"webhook receiver with dedupe and audit"``.
            limit: maximum compositions to return (1-5, capped at 5).

        Returns:
            Ranked list of ``{primitives, rationale, score, source, name}``
            dicts. Pure retrieval — no LLM call inside the tool.
        """
        return _suggest(intent=intent, limit=limit)

    mcp_app.tool(
        name="fastapi_suggest_composition",
        tags={"discovery", "composition", "retrieval"},
    )(suggest_composition)
    return 2


# Generator-side discovery base dirs.  Order is stable (alphabetical by
# module path inside each base).  Each base dir is scanned recursively.
_GENERATOR_BASE_DIRS: tuple[str, ...] = (
    "benchmark",
    "core/tools",
    "generators",
    "modules/database/tools",
    "modules/security/tools",
)


def register_generators_from_metadata(mcp_app) -> int:
    """Scan generator-tier modules for ``MCP_TOOL`` metadata and register
    each entry function directly on the FastMCP app.

    FastMCP introspects ``inspect.signature(entry_fn)`` to build the tool
    parameter schema — no hand-coded wrappers.

    Returns:
        Number of generator tools registered.
    """
    count = 0
    seen: set[str] = set()

    for base in _GENERATOR_BASE_DIRS:
        base_dir = SKILL_ROOT / base
        if not base_dir.exists():
            continue
        for py_file in sorted(base_dir.rglob("*.py")):
            if py_file.name.startswith("__"):
                continue
            # Skip files that look like pytest tests UNLESS they contain
            # MCP_TOOL metadata (a quick substring check avoids importing
            # pytest-only modules for side effects).
            if py_file.name.startswith("test_"):
                try:
                    if "MCP_TOOL" not in py_file.read_text():
                        continue
                except OSError:
                    continue

            module_path = _file_to_module(py_file)
            try:
                mod = importlib.import_module(module_path)
            except Exception as exc:
                logger.debug("skip %s: %s", module_path, exc)
                continue

            mcp_meta = getattr(mod, "MCP_TOOL", None)
            if mcp_meta is None:
                continue

            name = mcp_meta["name"]
            if name in seen:
                logger.warning("duplicate MCP_TOOL name %s in %s", name, module_path)
                continue

            entry_name = mcp_meta.get("entry")
            if not entry_name:
                logger.warning("MCP_TOOL in %s missing 'entry'", module_path)
                continue
            entry_fn = getattr(mod, entry_name, None)
            if not callable(entry_fn):
                logger.warning(
                    "MCP_TOOL in %s has entry=%r but function not found",
                    module_path,
                    entry_name,
                )
                continue

            tags = set(mcp_meta.get("tags", []))
            annotations = mcp_meta.get("annotations")
            kwargs: dict = {"name": name, "tags": tags}
            if annotations:
                kwargs["annotations"] = annotations

            mcp_app.tool(**kwargs)(entry_fn)
            seen.add(name)
            count += 1
            logger.debug("registered generator tool: %s", name)

    return count


def _register_adapt_tool(mcp_app, meta: dict, entry_fn) -> None:
    """Register a single adapt tool on the FastMCP app.

    The wrapper translates MCP-style args (project_dir, dry_run) into
    ``ToolInput`` and calls the real function.
    """
    from adapt.contracts import ToolInput

    name = meta["name"]
    desc = meta.get("description", entry_fn.__doc__ or "")
    tags = set(meta.get("tags", []))

    def _make_wrapper(_entry_fn, _desc):
        def tool_wrapper(project_dir: str, dry_run: bool = False) -> dict:
            result = _entry_fn(ToolInput(project_dir=project_dir, dry_run=dry_run))
            return result.model_dump()

        tool_wrapper.__doc__ = _desc
        tool_wrapper.__name__ = name
        return tool_wrapper

    wrapper = _make_wrapper(entry_fn, desc)
    mcp_app.tool(name=name, tags=tags)(wrapper)


def _file_to_module(py_file: Path) -> str:
    """Convert a file path to a dotted module name relative to SKILL_ROOT."""
    rel = py_file.relative_to(SKILL_ROOT)
    return str(rel).replace("/", ".").removesuffix(".py")
