"""`fastapi_meta_compose` — the "last mile" tier-1 tool.

Given a set of primitives (or a recipe id), emit them PLUGGED TOGETHER
into a single `app/compositions/<slug>.py` exporting `install(app, ...)`.

Design contract: `/docs/research/COMPOSE_TOOL_DESIGN.md`.
Four-tier fallthrough (first match wins):

  1. adapter_reuse   — set-equality with one of the 16 FastAPI adapters
                       under `core/venous/_adapters/fastapi/*Adapter.py`.
                       Emit a thin call-site into the shipped adapter.
  2. tool_delegate   — set-equality with a catalog tool's
                       `primitives_used`. Return the tool name + pointer
                       instead of duplicating its output. No file written.
  3. recipe_template — set-match against one of 385 recipes in
                       `engine/index/catalog.json`. Emit a render-
                       friendly skeleton using the recipe's intent prose.
  4. ad_hoc          — no match; emit a skeleton with a visible WARNING
                       banner and `mode="ad_hoc"` + quality flag.

Envelope shape identical to the other tier-1 tools (ok/what_happened/
result/next_steps/elapsed_ms).

Scope discipline (load-bearing):
  - Pure INFRASTRUCTURE composition. If caller names a domain primitive
    (Aggregate / Specification / DomainEvent / BoundedContext /
    AntiCorruptionLayer / ValueObject), refuse and point at the agent's
    domain-authoring responsibility. Boundary is §5 of the design doc.
  - No mutation of `app/main.py`. Caller wires the returned `install()`
    call into main.py themselves.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from mcp_tools import owned_envelope
from mcp_tools.error_codes import require_code
from mcp_tools.path_guard import output_dir as guard_output_dir

TOOL = "hugr-compose"
SKILL_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = SKILL_ROOT / "engine" / "index" / "catalog.json"
ADAPTERS_DIR = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"

# Domain-shaped primitive names that belong to the agent's author-it-yourself
# layer, not to infra composition. Compose refuses if any is passed.
DOMAIN_PRIMITIVE_BLACKLIST: frozenset[str] = frozenset(
    {
        "Aggregate",
        "Specification",
        "DomainEvent",
        "BoundedContext",
        "AntiCorruptionLayer",
        "ValueObject",
        "CommandBus",
        "QueryBus",
        "CommandQuerySeparator",
    }
)


# ---------------------------------------------------------------------------
# Envelope (mirrors tier1._envelope — intentional duplication for decoupling)
# ---------------------------------------------------------------------------


def _envelope(
    *,
    ok: bool,
    what: str,
    result: Any,
    next_steps: list[str],
    t0: float,
    code: str | None = None,
    owned: dict | None = None,
) -> dict:
    return {
        "ok": ok,
        "code": require_code(ok, code),
        "what_happened": what,
        "result": result,
        "next_steps": next_steps[:5],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        **(owned or {}),
    }


def _load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Adapter inspection — scan `_adapters/fastapi/*Adapter.py` for which
# primitives each shipped adapter uses (AST imports). Cached per-process.
# ---------------------------------------------------------------------------

_ADAPTER_INDEX: dict[str, frozenset[str]] | None = None


def _adapter_index() -> dict[str, frozenset[str]]:
    """Return {adapter_stem: frozenset(registered_primitive_names)} for every shipped adapter.

    Only names that exist in the catalog's primitives registry are kept;
    internal helpers (InMemory*, TrustAnchor, *Error, etc.) are filtered
    out so set-equality matching against caller-requested primitives works.
    """
    global _ADAPTER_INDEX
    if _ADAPTER_INDEX is not None:
        return _ADAPTER_INDEX
    idx: dict[str, frozenset[str]] = {}
    if not ADAPTERS_DIR.exists():
        _ADAPTER_INDEX = idx
        return idx
    try:
        registered = {p["name"] for p in _load_catalog()["primitives"]}
    except (OSError, json.JSONDecodeError, KeyError):
        registered = set()
    for py in sorted(ADAPTERS_DIR.glob("*.py")):
        if py.name.startswith(("_", "test_")):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        prims: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("core.venous.")
            ):
                parts = node.module.split(".")
                # Module path is core.venous.<ns>.<Name>.<Name>; index 3 is <Name>
                if len(parts) >= 4 and parts[3] in registered:
                    prims.add(parts[3])
        idx[py.stem] = frozenset(prims)
    _ADAPTER_INDEX = idx
    return idx


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_inputs(
    primitives: list[str] | None,
    recipe_id: str | None,
    catalog: dict,
) -> tuple[list[str], str | None, tuple[str, str] | None]:
    """Resolve (primitives, recipe_id) against the catalog.

    Returns (resolved_primitives, resolved_recipe_id, (error_code, error_msg) or None).
    """
    registered_prim_names = {p["name"] for p in catalog["primitives"]}
    recipes_by_id = {r["id"]: r for r in catalog["recipes"]}

    # Case A — recipe_id passed
    if recipe_id is not None:
        rec = recipes_by_id.get(recipe_id)
        if rec is None:
            return (
                [],
                None,
                ("unknown-recipe", f"unknown recipe_id {recipe_id!r}. Call fastapi_meta_search to find a valid id."),
            )
        recipe_prims = list(rec["primitives"])
        # If caller ALSO passed primitives, treat as subset-assertion.
        if primitives is not None:
            missing = set(primitives) - set(recipe_prims)
            if missing:
                return (
                    [],
                    None,
                    (
                        "recipe-mismatch",
                        f"recipe {recipe_id} does not contain primitives {sorted(missing)}; "
                        f"recipe's primitives are {sorted(recipe_prims)}.",
                    ),
                )
        return (recipe_prims, recipe_id, None)

    # Case B — only primitives passed
    if not primitives:
        return ([], None, ("missing-selection", "pass either recipe_id or primitives (non-empty list)."))
    unknown = [p for p in primitives if p not in registered_prim_names]
    if unknown:
        return (
            [],
            None,
            ("unknown-primitive", f"unknown primitive name(s): {unknown}. Call fastapi_meta_search to find valid names."),
        )
    return (list(primitives), None, None)


def _check_domain_blacklist(primitives: list[str]) -> str | None:
    hits = sorted(set(primitives) & DOMAIN_PRIMITIVE_BLACKLIST)
    if not hits:
        return None
    return (
        f"domain-shaped primitive(s) {hits} cannot be composed via fastapi_meta_compose. "
        f"These belong to the agent's domain-authoring layer (Aggregate + Specification + "
        f"DomainEvent). Compose handles INFRASTRUCTURE plumbing only. Author the domain "
        f"rule as an Aggregate method first; then compose plumbing around it."
    )


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------


def _match_adapter(primitives_set: frozenset[str]) -> str | None:
    """Return the adapter stem (e.g. 'WebhookReceiverAdapter') whose
    primitive-import set EQUALS the caller's set, or None.
    """
    for stem, adapter_prims in _adapter_index().items():
        if adapter_prims == primitives_set and adapter_prims:
            return stem
    return None


def _match_tool(primitives_set: frozenset[str], catalog: dict) -> dict | None:
    """Return the catalog tool whose ``primitives_used`` EQUALS the caller's
    primitive set, or None.

    Prefer this over recipe_template because a matching tool is an
    already-tested code generator — calling it is strictly better than
    emitting a skeleton. Ties broken deterministically by tool name.
    """
    hits: list[dict] = []
    for t in catalog["tools"]:
        used = frozenset(t.get("primitives_used") or ())
        if used and used == primitives_set:
            hits.append(t)
    if not hits:
        return None
    return sorted(hits, key=lambda t: t["name"])[0]


def _match_recipe(primitives_set: frozenset[str], catalog: dict) -> dict | None:
    """Return the first recipe whose primitive set EQUALS the caller's, or
    the best subset match with ≥2 overlapping primitives. None on no match.
    """
    exact: list[dict] = []
    subset: list[dict] = []
    for r in catalog["recipes"]:
        rec_set = frozenset(r["primitives"])
        if rec_set == primitives_set:
            exact.append(r)
        elif rec_set <= primitives_set and len(rec_set) >= 2:
            subset.append(r)
    if exact:
        # Deterministic choice: id-alphabetical
        return sorted(exact, key=lambda r: r["id"])[0]
    if subset:
        # Prefer the largest subset; tie-break by id.
        subset.sort(key=lambda r: (-len(r["primitives"]), r["id"]))
        return subset[0]
    return None


# ---------------------------------------------------------------------------
# Emitters — deterministic, style-matched to examples/02-webhook-sink/
# ---------------------------------------------------------------------------


def _primitive_import_line(name: str, catalog_primitives: list[dict]) -> str:
    """`from core.venous.<ns>.<Name>.<Name> import <Name>` form."""
    for p in catalog_primitives:
        if p["name"] == name:
            ns = p["namespace"]
            return f"from core.venous.{ns}.{name}.{name} import {name}"
    # Fallback if somehow primitive not in registry (shouldn't happen after validation).
    return f"# TODO: primitive {name} not resolved in registry"


def _emit_adapter_reuse(
    adapter_stem: str,
    primitives: list[str],
    mount_path: str,
    slug: str,
) -> str:
    """Emit a thin wrapper that calls into the shipped adapter."""
    adapter_class = adapter_stem
    return f'''"""{slug} — shipped adapter reuse ({adapter_stem}).

Generated by fastapi_meta_compose (mode=adapter_reuse).
Primitives composed: {", ".join(primitives)}.
"""
from __future__ import annotations

from fastapi import FastAPI

from core.venous._adapters.fastapi.{adapter_stem} import {adapter_class}


def install(app: FastAPI, *, mount_path: str = {mount_path!r}) -> dict:
    """Wire the shipped {adapter_stem} onto *app* at {{mount_path}}."""
    adapter = {adapter_class}()
    adapter.install(app, mount_path=mount_path)
    app.state.{slug} = adapter
    return {{"adapter": adapter, "mount_path": mount_path}}
'''


def _emit_recipe_template(
    recipe: dict,
    primitives: list[str],
    mount_path: str,
    slug: str,
    catalog_primitives: list[dict],
) -> str:
    """Emit a vetted-recipe skeleton with the intent prose as module docstring."""
    imports = "\n".join(_primitive_import_line(p, catalog_primitives) for p in primitives)
    wiring_summary = _sanitize_for_comment(recipe.get("intent") or recipe.get("description", ""))
    instance_lines = "\n    ".join(f"{_snake(p)} = {p}()" for p in primitives)
    state_lines = ", ".join(f'"{_snake(p)}": {_snake(p)}' for p in primitives)
    return f'''"""{slug} — recipe-backed composition.

Generated by fastapi_meta_compose (mode=recipe_template, recipe={recipe["id"]}).
Primitives composed: {", ".join(primitives)}.

Intent (from the primitive catalog's Compose-with section):
    {wiring_summary}
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

{imports}


def install(app: FastAPI, *, mount_path: str = {mount_path!r}) -> dict:
    """Wire {", ".join(primitives)} onto *app* at {{mount_path}}.

    TODO: customize the route handler body below with your business logic.
    The primitives are instantiated with defaults — swap for your
    production variants (persistent store, real crypto, etc.) as needed.
    """
    {instance_lines}

    router = APIRouter()

    @router.post(mount_path)
    async def _handler() -> dict:
        # TODO: replace with your compose-with wiring per the recipe above.
        return {{"ok": True, "mount_path": mount_path}}

    app.include_router(router)
    app.state.{slug} = {{{state_lines}, "mount_path": mount_path}}
    return app.state.{slug}
'''


def _emit_ad_hoc(
    primitives: list[str],
    mount_path: str,
    slug: str,
    catalog_primitives: list[dict],
) -> str:
    """Emit a skeleton with a visible WARNING banner."""
    imports = "\n".join(_primitive_import_line(p, catalog_primitives) for p in primitives)
    instance_lines = "\n    ".join(f"{_snake(p)} = {p}()" for p in primitives)
    state_lines = ", ".join(f'"{_snake(p)}": {_snake(p)}' for p in primitives)
    return f'''"""{slug} — ad-hoc composition (UNVERIFIED).

Generated by fastapi_meta_compose (mode=ad_hoc).
Primitives composed: {", ".join(primitives)}.

⚠️  WARNING: no canonical recipe matched this primitive set, and no
    shipped FastAPI adapter wires this exact combination. This
    composition is a SKELETON only — you must complete the wiring and
    verify the composition against the primitives' Compose-with
    invariants before shipping.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

{imports}


def install(app: FastAPI, *, mount_path: str = {mount_path!r}) -> dict:
    """⚠️  AD-HOC composition — verify before deploying.

    Wire {", ".join(primitives)} onto *app*. Customize freely.
    """
    {instance_lines}

    router = APIRouter()

    @router.post(mount_path)
    async def _handler() -> dict:
        # TODO: implement the composition logic for your domain.
        return {{"ok": True, "warning": "ad_hoc composition — verify wiring"}}

    app.include_router(router)
    app.state.{slug} = {{{state_lines}, "mount_path": mount_path}}
    return app.state.{slug}
'''


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _snake(pascal: str) -> str:
    """PascalCase → snake_case."""
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", pascal).lower()
    # Avoid Python keywords / builtins collision.
    if s in {"cls", "self"}:
        s += "_"
    return s


def _derive_slug(recipe_id: str | None, primitives: list[str], name: str | None) -> str:
    """Compute a Python-identifier-safe slug.

    Slug must be a valid Python attribute name (starts with letter/underscore,
    contains only [a-z0-9_]) because we emit `app.state.<slug>`.
    """

    def _py_safe(s: str) -> str:
        s = re.sub(r"[^a-z0-9_]", "_", s.lower()).strip("_")
        if not s:
            return "composition"
        # Python identifier must start with letter or underscore, not digit
        if s[0].isdigit():
            s = f"c_{s}"
        return s

    if name:
        return _py_safe(name)
    if recipe_id:
        return _py_safe(recipe_id.split("__")[-1])
    h = hashlib.sha1("|".join(sorted(primitives)).encode()).hexdigest()[:10]
    return f"composition_{h}"


def _sanitize_for_comment(text: str) -> str:
    return (text or "").replace('"""', "'''").replace("*/", " /").strip()[:500]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _ast_validate(source: str) -> tuple[bool, str]:
    try:
        ast.parse(source)
        return (True, "")
    except SyntaxError as exc:
        return (False, f"ast parse error at line {exc.lineno}: {exc.msg}")


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_meta_compose",
    "description": (
        "Last-mile composition tool. Given a set of primitives (or a recipe_id), "
        "emit them PLUGGED TOGETHER into app/compositions/<slug>.py exporting "
        "install(app, *, mount_path). Three-tier fallthrough:\n"
        "  mode=adapter_reuse   — set matches a shipped FastAPI adapter\n"
        "  mode=recipe_template — set matches one of 385 recipes\n"
        "  mode=ad_hoc          — no match; emits a WARNING-banner skeleton\n"
        "Scope is INFRASTRUCTURE plumbing only; refuses domain-shaped primitives "
        "(Aggregate, Specification, DomainEvent, …) — those are authored by "
        "agent as separate domain code. Use AFTER fastapi_meta_search finds "
        "the primitives you need."
    ),
    "tags": ["meta", "compose"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_meta_compose",
}


def fastapi_meta_compose(
    output_dir: str,
    *,
    recipe_id: str | None = None,
    primitives: list[str] | None = None,
    name: str | None = None,
    mount_path: str = "/",
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """See MCP_TOOL description."""
    t0 = time.perf_counter()
    try:
        output_dir = guard_output_dir(output_dir)
    except ValueError as exc:
        return _envelope(
            ok=False,
            code="path-rejected",
            owned=owned_envelope.blocked(TOOL, "path-rejected"),
            what=str(exc),
            result={},
            next_steps=["Pass an output_dir inside the native worktree."],
            t0=t0,
        )

    # 1. Load catalog + validate inputs
    catalog = _load_catalog()
    resolved_prims, resolved_recipe, err = _validate_inputs(primitives, recipe_id, catalog)
    if err is not None:
        return _envelope(
            ok=False,
            code=err[0],
            owned=owned_envelope.blocked(TOOL, err[0]),
            what=err[1],
            result={},
            next_steps=[
                "fastapi_meta_search(query='<what you need>') to find valid names.",
                "fastapi_meta_describe(name='<candidate>') to see the schema.",
            ],
            t0=t0,
        )

    # 2. Domain-boundary refusal
    err = _check_domain_blacklist(resolved_prims)
    if err is not None:
        return _envelope(
            ok=False,
            code="domain-boundary",
            owned=owned_envelope.blocked(TOOL, "domain-boundary"),
            what=err,
            result={},
            next_steps=[
                "Author your Aggregate + Specification first (agent responsibility).",
                "Then call fastapi_meta_compose with the INFRASTRUCTURE primitives only.",
            ],
            t0=t0,
        )

    # 3. Resolve slug + target file
    slug = _derive_slug(resolved_recipe, resolved_prims, name)
    target_file = Path(output_dir) / "app" / "compositions" / f"{slug}.py"

    # The change inventory is what the filesystem shows under <output_dir>/app after the call, not what this
    # function believes it wrote.
    before = owned_envelope.snapshot(output_dir, "app")

    if target_file.exists() and not force:
        return _envelope(
            ok=False,
            code="target-exists",
            owned=owned_envelope.blocked(TOOL, "target-exists"),
            what=f"composition already exists at {target_file.relative_to(output_dir) if target_file.is_relative_to(output_dir) else target_file}; pass force=True to overwrite",
            result={"slug": slug, "existing_path": str(target_file)},
            next_steps=[
                "Call again with force=True to overwrite.",
                "Or pass a different `name` to emit a parallel composition.",
            ],
            t0=t0,
        )

    # 4. Mode selection — first-match priority:
    #      adapter_reuse > tool_delegate > recipe_template > ad_hoc
    prim_set = frozenset(resolved_prims)

    adapter_stem = _match_adapter(prim_set)
    if adapter_stem is None and not recipe_id:
        # 4a. Tool delegation — if an indexed tool already emits exactly
        # this primitive set, don't duplicate its work. Return early with a
        # pointer so the agent can call that tool (which has tests,
        # MCP_TOOL metadata, and a stable entry signature). Only consulted
        # when no adapter matches; adapter is strictly better when both do.
        matching_tool = _match_tool(prim_set, catalog)
        if matching_tool is not None:
            return _envelope(
                ok=True,
                owned=owned_envelope.owned(
                    tool=TOOL,
                    status="blocked",
                    effects="none",
                    mode="tool_delegate",
                    code="UNSUPPORTED_OUTPUT",
                ),
                what=(
                    f"tool {matching_tool['name']!r} already emits this exact "
                    f"primitive set ({len(resolved_prims)} primitives) — call "
                    f"it directly instead of composing a skeleton"
                ),
                result={
                    "mode": "tool_delegate",
                    "delegate_tool": matching_tool["name"],
                    "delegate_module": matching_tool["module_path"],
                    "primitives_used": list(resolved_prims),
                    "files_written": [],
                    "validation_report": {
                        "ast_parse": True,
                        "ast_error": "",
                        "primitives_resolved": True,
                        "mode_quality": "HIGH",
                    },
                },
                next_steps=[
                    f"Call {matching_tool['name']}(output_dir={output_dir!r}, …) — see fastapi_meta_describe for its schema.",
                    "Pass `recipe_id=…` to this tool if you want a skeleton anyway.",
                ],
                t0=t0,
            )

    if adapter_stem is not None:
        mode = "adapter_reuse"
        source = _emit_adapter_reuse(adapter_stem, resolved_prims, mount_path, slug)
        recipe_used = None
        wiring_summary = f"Shipped {adapter_stem} wires {', '.join(resolved_prims)}."
    else:
        recipe = _match_recipe(prim_set, catalog)
        if recipe is not None:
            mode = "recipe_template"
            source = _emit_recipe_template(
                recipe,
                resolved_prims,
                mount_path,
                slug,
                catalog["primitives"],
            )
            recipe_used = recipe["id"]
            wiring_summary = _sanitize_for_comment(
                recipe.get("intent") or recipe.get("description", "")
            )[:160]
        else:
            mode = "ad_hoc"
            source = _emit_ad_hoc(
                resolved_prims,
                mount_path,
                slug,
                catalog["primitives"],
            )
            recipe_used = None
            wiring_summary = f"Ad-hoc composition of {', '.join(resolved_prims)} (unverified)."

    # 5. AST validate the emission before writing
    ok_ast, ast_err = _ast_validate(source)
    validation_report = {
        "ast_parse": ok_ast,
        "ast_error": ast_err if not ok_ast else "",
        "primitives_resolved": True,
        "mode_quality": (
            "HIGH" if mode == "adapter_reuse" else "MEDIUM" if mode == "recipe_template" else "LOW"
        ),
    }
    if not ok_ast:
        return _envelope(
            ok=False,
            code="invalid-output",
            owned=owned_envelope.owned(
                tool=TOOL,
                status="failed",
                effects="none",
                mode=mode,
                code="INVALID_PRODUCER_RESULT",
                producer_code="invalid-output",
            ),
            what=f"emitted source has syntax error: {ast_err}",
            result={
                "mode": mode,
                "composition_source": source,
                "validation_report": validation_report,
            },
            next_steps=[
                "This is a bug in fastapi_meta_compose — file an issue with the primitives list.",
            ],
            t0=t0,
        )

    # 6. Write (unless dry_run).
    files_written: list[str] = []
    if not dry_run:
        init = target_file.parent / "__init__.py"
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create unless forced: a file that appeared after the check above must not be overwritten.
            with open(target_file, "w" if force else "x", encoding="utf-8") as handle:
                handle.write(source)
            # Emit an __init__.py to make compositions/ a package.
            if not init.exists():
                init.write_text("", encoding="utf-8")
                files_written.append(str(init.relative_to(output_dir)))
            files_written.append(str(target_file.relative_to(output_dir)))
        except OSError as exc:
            after = owned_envelope.snapshot(output_dir, "app")
            if isinstance(exc, FileExistsError) and target_file.is_file():
                producer, f4 = "target-exists", "OUTPUT_CONFLICT"
            elif isinstance(exc, PermissionError):
                producer, f4 = "write-failed", "PERMISSION_DENIED"
            else:
                producer, f4 = "write-failed", "PRODUCER_FAILED"
            return _envelope(
                ok=False,
                code=producer,
                owned=owned_envelope.failed(TOOL, f4, producer, before, after, mode),
                what=f"could not write composition: {exc.__class__.__name__}",
                result={"slug": slug, "mode": mode},
                next_steps=["Reconcile app/compositions before calling again; the write is not retried."],
                t0=t0,
            )
    seen = owned_envelope.changes(before, owned_envelope.snapshot(output_dir, "app"))
    relative_target = str(target_file.relative_to(output_dir))
    kind = "composition" if mode == "adapter_reuse" else "skeleton"
    if dry_run and seen == []:
        canonical = owned_envelope.owned(
            tool=TOOL,
            status="previewed",
            effects="none",
            mode=mode,
            artifact_kind=kind,
            artifacts=[{"kind": "source", "path": relative_target, "content": source}],
            planned_files=[relative_target],
        )
    elif not dry_run and seen:
        canonical = owned_envelope.owned(
            tool=TOOL, status="generated", effects="observed", observed_changes=seen, mode=mode, artifact_kind=kind
        )
    else:
        # A dry run that changed files, or a write nobody can see: the result cannot be trusted.
        canonical = owned_envelope.owned(
            tool=TOOL,
            status="failed",
            effects="unknown",
            observed_changes=seen,
            mode=mode,
            code="INVALID_PRODUCER_RESULT",
        )

    # 7. Return envelope
    result = {
        "mode": mode,
        "slug": slug,
        "composition_source": source,
        "files_written": files_written,
        "primitives_used": [
            {
                "name": p,
                "module": _module_for(p, catalog["primitives"]),
            }
            for p in resolved_prims
        ],
        "recipe_used": recipe_used,
        "wiring_summary": wiring_summary,
        "mount": {"router_var": "router", "path": mount_path},
        "validation_report": validation_report,
    }
    return _envelope(
        ok=True,
        owned=canonical,
        what=(
            f"composed {len(resolved_prims)} primitive(s) via mode={mode}; "
            f"{'dry-run (no files)' if dry_run else f'wrote {len(files_written)} file(s)'}"
        ),
        result=result,
        next_steps=[
            f"In app/main.py: from app.compositions.{slug} import install; install(app)",
            "Call fastapi_meta_audit() after wiring to verify contract drift.",
            (
                "Primitives must be copied to the target project — "
                "if not yet, call fastapi_auth(action='primitive', ...) for auth "
                "primitives, or scaffold with fastapi_meta_scaffold first."
            ),
        ],
        t0=t0,
    )


def _module_for(name: str, primitives_catalog: list[dict]) -> str:
    for p in primitives_catalog:
        if p["name"] == name:
            return f"core.venous.{p['namespace']}.{name}.{name}"
    return f"core.venous.?.{name}.{name}"
