"""Auto-discover and register MCP tools from adapt/ and generators/.

Convention: any Python module containing a top-level ``MCP_TOOL`` dict
gets registered as an MCP tool.  The dict must have:

  - name: str       -- MCP tool name (e.g. "fastapi_add_websocket_chat")
  - description: str -- one-line summary
  - tags: list[str]  -- category tags
  - entry: str       -- function name in the module (default: module filename stem)

Generators use a separate discovery path since their MCP metadata
is defined differently (they are imported directly in mcp/generators.py).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
SKILL_ROOT = Path(__file__).resolve().parent.parent


def discover_and_register(mcp_app) -> int:
    """Scan adapt/ subdirectories for modules with MCP_TOOL metadata
    and register them.  Also imports and registers generators from
    mcp/generators.py.

    Returns:
        Number of tools registered.
    """
    count = 0

    # --- Auto-discover adapt tools ---
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
            # Skip test files, but NOT test_coverage_gaps.py which is a
            # real tool (its test file is test_test_coverage_gaps.py)
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

    # --- Register generators (custom parameter signatures) ---
    from mcp_tools.generators import register_generators

    count += register_generators(mcp_app)

    logger.info("registered %d MCP tools total", count)
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

    # Build the wrapper with a closure over the real entry_fn.
    # We need a factory to capture the variables correctly in a loop.
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
