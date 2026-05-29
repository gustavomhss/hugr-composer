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

import contextvars
import importlib
import json
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)
SKILL_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Session-scoped bundle activation (schema v2 / ADR-0003)
#
# Default tools/list surface = the eight tier-1 meta tools. Activating a
# bundle via fastapi_meta_activate_bundle adds that bundle's tools to the
# list response for the current session. Stored in a ContextVar so we
# stay isolated per event loop / per request (multi-tenant friendly when
# the bearer-forwarding pattern lands).
#
# Activation is CLUTTER management, not access control: tools/call still
# resolves any tool by name regardless of activation, and the auth/scope
# gate still decides what actually executes. See ADR-0003 §Decision.
# ---------------------------------------------------------------------------

_ACTIVE_BUNDLES: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    "active_bundles", default=frozenset()
)

# Set of tool names that ALWAYS appear in tools/list. Kept here so the
# filter and the audit can converge on a single source of truth.
#
# Includes:
#   - the eight tier-1 meta tools from mcp_tools/tier1.py
#   - the compose tool from mcp_tools/compose.py
#   - the two legacy discovery tools required by CONTRACT §B2.1/§B2.2
#   - the nine domain-tree dispatchers (`fastapi_<domain>`) registered by
#     register_tree_tools — these are the agent's primary domain
#     entry-points and stay tier-1 visible regardless of which bundle
#     was activated. They live OUTSIDE the catalog (catalog tracks the
#     per-`<verb>_<noun>` surface that the dispatchers route to), so
#     they must be allowlisted by name.
ALWAYS_VISIBLE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "fastapi_meta_home",
        "fastapi_meta_search",
        "fastapi_meta_describe",
        "fastapi_meta_scaffold",
        "fastapi_meta_audit",
        "fastapi_meta_verify",
        "fastapi_meta_list_bundle",
        "fastapi_meta_activate_bundle",
        "fastapi_meta_compose",
        "find_primitive",
        "suggest_composition",
        # Domain-tree dispatchers (mcp_tools/tree/*.py).
        "fastapi_auth",
        "fastapi_data",
        "fastapi_api",
        "fastapi_realtime",
        "fastapi_resiliency",
        "fastapi_observability",
        "fastapi_compliance",
        "fastapi_deployment",
        "fastapi_testing",
    }
)

# Kept for back-compat with any caller importing TIER1_TOOL_NAMES (the
# original set before WAVE-0-F2's allowlist expansion to include tree
# dispatchers). The audit + filter both read ALWAYS_VISIBLE_TOOL_NAMES.
TIER1_TOOL_NAMES = ALWAYS_VISIBLE_TOOL_NAMES


def activate_bundle(bundle_name: str) -> frozenset[str]:
    """Add `bundle_name` to the active set in the current context.

    Returns the new active set. Idempotent. Safe to call from any tool
    function — the ContextVar is the only mutable state.
    """
    current = _ACTIVE_BUNDLES.get()
    new = frozenset(current | {bundle_name})
    _ACTIVE_BUNDLES.set(new)
    return new


def get_active_bundles() -> frozenset[str]:
    """Return the currently-active bundle set (frozen)."""
    return _ACTIVE_BUNDLES.get()


def reset_active_bundles() -> None:
    """Clear the active bundle set. Test/maintenance hook."""
    _ACTIVE_BUNDLES.set(frozenset())


def _load_catalog_tool_bundle_map() -> dict[str, str]:
    """Return {tool_name: bundle_name} from catalog.json.

    Cached at call site; cheap enough to re-read each time tools/list is
    invoked, but for hot paths use the FastMCP middleware which memoises.
    """
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog_path.exists():
        return {}
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {t.get("name"): t.get("bundle", "") for t in data.get("tools", [])}


def _filter_tools_for_list(all_tools: Iterable, *, name_attr: str = "name"):
    """Return the tools that should appear in tools/list for this session.

    Rule:
      - Always include tier-1 meta tools (TIER1_TOOL_NAMES).
      - Include any tool whose `bundle` is in the active set.

    Pure: reads _ACTIVE_BUNDLES + catalog.json, mutates nothing. Used by
    the FastMCP middleware in `BundleVisibilityMiddleware.on_list_tools`.

    `all_tools` is an iterable of objects that have a `name_attr` field;
    works for both FastMCP Tool dataclasses and plain dicts (dicts are
    accessed via `[name_attr]`).
    """
    active = _ACTIVE_BUNDLES.get()
    catalog_map = _load_catalog_tool_bundle_map()

    def _name(t) -> str:
        if isinstance(t, dict):
            return t.get(name_attr, "")
        return getattr(t, name_attr, "")

    out = []
    for tool in all_tools:
        n = _name(tool)
        if n in ALWAYS_VISIBLE_TOOL_NAMES:
            out.append(tool)
            continue
        bundle = catalog_map.get(n)
        if bundle and bundle in active:
            out.append(tool)
    return out


def install_bundle_visibility_middleware(mcp_app) -> None:
    """Wire the on_list_tools filter into the FastMCP app.

    Implementation: a FastMCP Middleware subclass whose `on_list_tools`
    hook intercepts the framework's default response and applies
    `_filter_tools_for_list`. Tools/call is NOT touched — activation is
    clutter management, not access control.

    Idempotent: safe to call multiple times; subsequent calls add no
    additional middleware instances (we mark the app with an attribute).
    """
    if getattr(mcp_app, "_hugr_bundle_filter_installed", False):
        return
    try:
        from fastmcp.server.middleware import Middleware
    except ImportError:  # pragma: no cover — fastmcp absent in some test envs
        return

    class BundleVisibilityMiddleware(Middleware):
        """Filter tools/list responses by the active bundle set."""

        async def on_list_tools(self, context, call_next):
            tools = await call_next(context)
            try:
                return _filter_tools_for_list(tools)
            except Exception:  # noqa: BLE001
                # Filtering must never break list_tools; on error, fall
                # back to the unfiltered surface (fail-open, since this
                # is clutter management, not access control).
                logger.exception("bundle visibility filter failed; returning full list")
                return tools

    mcp_app.add_middleware(BundleVisibilityMiddleware())
    mcp_app._hugr_bundle_filter_installed = True


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
            # Skip helpers under a dir-form tool (add_<tool>/foo.py).
            # We pick up the dir-form tool itself via its __init__.py below.
            if py_file.parent.name.startswith("add_") and py_file.name != "__init__.py":
                continue
            if py_file.name.startswith("__") and py_file.name != "__init__.py":
                continue
            if py_file.name.startswith("test_") and py_file.name != "test_coverage_gaps.py":
                continue

            # For dir-form tools (add_<tool>/__init__.py), import the package
            # itself (drop the .__init__ suffix) so we do not get a second
            # module object that duplicates the same MCP_TOOL name.
            if py_file.name == "__init__.py":
                module_path = ".".join(py_file.parent.relative_to(SKILL_ROOT).parts)
                entry_name_default = py_file.parent.name
            else:
                module_path = _file_to_module(py_file)
                entry_name_default = py_file.stem

            try:
                mod = importlib.import_module(module_path)
            except Exception as exc:
                logger.debug("skip %s: %s", module_path, exc)
                continue

            mcp_meta = getattr(mod, "MCP_TOOL", None)
            if mcp_meta is None:
                continue

            entry_name = mcp_meta.get("entry", entry_name_default)
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
    count += register_tree_tools(mcp_app)

    logger.info("registered %d MCP tools total", count)
    return count


def register_tree_tools(mcp_app) -> int:
    """Register the domain-tree dispatchers (Phase 6 tree variant).

    One MCP tool per domain, each with an `action` param that routes
    to bundle / slices / primitives. Ships the full set of 9 domain
    dispatchers: auth, data, api, realtime, resiliency, observability,
    compliance, deployment, testing. All mirror the canonical
    `mcp_tools/tree/auth.py` template.
    """
    from mcp_tools.tree.api import MCP_TOOL as API_META
    from mcp_tools.tree.api import fastapi_api
    from mcp_tools.tree.auth import MCP_TOOL as AUTH_META
    from mcp_tools.tree.auth import fastapi_auth
    from mcp_tools.tree.compliance import MCP_TOOL as COMPLIANCE_META
    from mcp_tools.tree.compliance import fastapi_compliance
    from mcp_tools.tree.data import MCP_TOOL as DATA_META
    from mcp_tools.tree.data import fastapi_data
    from mcp_tools.tree.deployment import MCP_TOOL as DEPLOYMENT_META
    from mcp_tools.tree.deployment import fastapi_deployment
    from mcp_tools.tree.observability import MCP_TOOL as OBSERVABILITY_META
    from mcp_tools.tree.observability import fastapi_observability
    from mcp_tools.tree.realtime import MCP_TOOL as REALTIME_META
    from mcp_tools.tree.realtime import fastapi_realtime
    from mcp_tools.tree.resiliency import MCP_TOOL as RESILIENCY_META
    from mcp_tools.tree.resiliency import fastapi_resiliency
    from mcp_tools.tree.testing import MCP_TOOL as TESTING_META
    from mcp_tools.tree.testing import fastapi_testing

    dispatchers = (
        (fastapi_auth, AUTH_META),
        (fastapi_data, DATA_META),
        (fastapi_api, API_META),
        (fastapi_realtime, REALTIME_META),
        (fastapi_resiliency, RESILIENCY_META),
        (fastapi_observability, OBSERVABILITY_META),
        (fastapi_compliance, COMPLIANCE_META),
        (fastapi_deployment, DEPLOYMENT_META),
        (fastapi_testing, TESTING_META),
    )
    for fn, meta in dispatchers:
        mcp_app.tool(
            name=meta["name"],
            tags=set(meta.get("tags", [])),
        )(fn)
    return len(dispatchers)


def register_tier1_tools(mcp_app) -> int:
    """Register the tier-1 meta tools (dual-index design + ADR-0003).

    Always-loaded; primacy position. Eight of them live in
    `mcp_tools/tier1.py` (home, search, describe, scaffold, audit,
    verify, list_bundle, activate_bundle); compose lives in
    `mcp_tools/compose.py`. The two list_bundle / activate_bundle tools
    were added in WAVE-0-F2 alongside catalog schema v2.

    Also installs the bundle-visibility middleware so the activation
    contextvar (see `_ACTIVE_BUNDLES` above) actually filters
    tools/list. Tools/call is NOT touched — activation is clutter
    management, not access control.
    """
    from mcp_tools.compose import MCP_TOOL as MCP_TOOL_COMPOSE
    from mcp_tools.compose import fastapi_meta_compose
    from mcp_tools.tier1 import (
        MCP_TOOL as MCP_TOOL_HOME,
    )
    from mcp_tools.tier1 import (
        MCP_TOOL_ACTIVATE_BUNDLE,
        MCP_TOOL_AUDIT,
        MCP_TOOL_DESCRIBE,
        MCP_TOOL_LIST_BUNDLE,
        MCP_TOOL_SCAFFOLD,
        MCP_TOOL_SEARCH,
        MCP_TOOL_VERIFY,
        fastapi_meta_activate_bundle,
        fastapi_meta_audit,
        fastapi_meta_describe,
        fastapi_meta_home,
        fastapi_meta_list_bundle,
        fastapi_meta_scaffold,
        fastapi_meta_search,
        fastapi_meta_verify,
    )

    pairs = (
        (fastapi_meta_home, MCP_TOOL_HOME),
        (fastapi_meta_search, MCP_TOOL_SEARCH),
        (fastapi_meta_describe, MCP_TOOL_DESCRIBE),
        (fastapi_meta_scaffold, MCP_TOOL_SCAFFOLD),
        (fastapi_meta_compose, MCP_TOOL_COMPOSE),
        (fastapi_meta_audit, MCP_TOOL_AUDIT),
        (fastapi_meta_verify, MCP_TOOL_VERIFY),
        (fastapi_meta_list_bundle, MCP_TOOL_LIST_BUNDLE),
        (fastapi_meta_activate_bundle, MCP_TOOL_ACTIVATE_BUNDLE),
    )
    for fn, meta in pairs:
        mcp_app.tool(
            name=meta["name"],
            tags=set(meta.get("tags", [])),
        )(fn)

    install_bundle_visibility_middleware(mcp_app)
    return len(pairs)


def register_discovery_tools(mcp_app) -> int:
    """Register legacy BM25 discovery tools (CONTRACT §B2.1, §B2.2).

    The MCP_TOOL metadata dicts live alongside the entry functions in
    `engine/discovery/find_primitive.py` and `engine/discovery/compose.py`;
    this function is the runtime-registration sidecar so the MCP server
    binds the callables while the manifest scanner indexes the metadata.
    Single source of truth = the MCP_TOOL dict.
    """
    from engine.discovery import find_primitive as _find
    from engine.discovery import suggest_composition as _suggest
    from engine.discovery.compose import MCP_TOOL as COMP_META
    from engine.discovery.find_primitive import MCP_TOOL as PRIM_META

    def find_primitive(concern: str = "", query: str = "", limit: int = 10) -> list[dict]:
        """Search the primitive catalog by concern and free-text query.

        Returns a BM25-ranked list of ``{name, namespace, concern, purpose,
        score}`` dicts. Pure retrieval — no LLM call inside the tool.
        """
        return _find(concern=concern, query=query, limit=limit)

    mcp_app.tool(
        name=PRIM_META["name"],
        tags=set(PRIM_META.get("tags", [])),
    )(find_primitive)

    def suggest_composition(intent: str, limit: int = 5) -> list[dict]:
        """Rank compose-with recipes against a free-text intent.

        Returns a ranked list of ``{primitives, rationale, score, source,
        name}`` dicts. Pure retrieval — no LLM call inside the tool.
        """
        return _suggest(intent=intent, limit=limit)

    mcp_app.tool(
        name=COMP_META["name"],
        tags=set(COMP_META.get("tags", [])),
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
