"""CONTRACT.md §B0.11 — admin/diagnostic routes require auth.

CONTRACT.md scope: §B0.11 ``admin_routes_require_auth`` — AST-scan every
``*route*.py.tmpl`` / ``*routes*.py.tmpl`` under
``skills/SKILL-001-fastapi-production/adapt/`` AND every adapter module
under ``skills/SKILL-001-fastapi-production/core/venous/_adapters/fastapi/``
(plain ``*.py``, excluding ``__init__.py`` and ``_test_*``/``test_*``
files), and REJECT any ``@router.<verb>(...)`` whose effective path
(router ``prefix=`` + decorator ``path``) matches the admin-path regex
AND whose handler signature carries no auth dependency.

Origin: ROUND5_6_TRIAGE §3 P2 — "Admin/diagnostic routes lack
authentication (≥15 occurrences)". Closes ~15 BLOCKER findings.

Phase A1 (2026-05-31, #118 + #120):
  * Adapter scope: second pass over ``core/venous/_adapters/fastapi/*.py``
    closes R5-S1-F1 (``AuditLogAdapter`` ``/audit-logs/``) + R5-O2-D7
    (``EventSourcedStoreAdapter`` ``/events/*``) which previously hid in
    the un-scanned adapter tree (#118).
  * Regex keywords: added ``outbox|compliance|refunds|presence|webhook|
    websocket|notif`` — verified against ``add_outbox_pattern``
    (``/outbox/metrics``, ``/outbox/dlq``) and ``add_websocket_presence``
    (``/presence/online``, ``/presence/{user_id}``) (#120).
  * Prefix resolution: when ``router = APIRouter(prefix=<Name>)`` references
    a parameter of the enclosing ``def`` whose default is a string literal
    (the adapter ``install(..., prefix: str = "/events")`` pattern), we
    resolve through the default. Required to catch adapter violators.

This module lives outside the ``phase*`` cohesion (template-AST scanning
is a different concern from per-phase identity / primitive / catalog
checks); it only imports from ``_common`` so the WP-16 §3 invariant I12
("phase modules never import each other") is preserved.

Trade-offs (recorded for posterity):

* **File-level waiver, not per-route.** ``_WAIVED_TOOLS`` exempts the
  whole template. Per-route exemption would be more surgical but YAGNI
  for the Wave-0 close-out; the waiver list IS the Wave-1 punch list.
* **Effective-path matching.** The spec regex anchors on ``^/...`` but
  FastAPI templates split the path across ``APIRouter(prefix=...)`` and
  the decorator's ``path=`` arg. We concatenate the two before
  regex-matching so the rule fires on the URL the user actually sees
  (e.g. ``prefix="/authz"`` + ``path="/check"`` → ``/authz/check``).
  Literal ``path``-only matching would silently miss every known
  violator.
* **Bypass marker.** A module-level ``_PUBLIC_ROUTE_JUSTIFICATION: str
  = "..."`` annotated assignment OR plain assignment exempts the whole
  file (per spec). This intentionally requires a written justification —
  not just a magic boolean — so the public-by-design intent is visible
  in code review.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._common import SKILL_ROOT

# ---------------------------------------------------------------------------
# WAIVER SET — tools that CURRENTLY violate B0.11 and are exempt while their
# fix-PRs land. Each entry is the leaf directory name under
# ``adapt/extend/<concern>/<tool>/templates/``. Every waived tool MUST get a
# follow-up PR adding the auth dependency (or, for honeypots, the
# ``_PUBLIC_ROUTE_JUSTIFICATION`` marker). This set is the Wave-1 backlog.
#
# Populated by running this rule against the catalog on 2026-05-30 at base
# commit 636ab57; 14 tools / 31 routes flagged. See PR body for the per-tool
# violating-route table.
#
# Wave-2 BATCH close-out (2026-05-31, fix/w2-batch-b011-all-admin-auth):
# All 11 remaining waivers closed in one PR — 10 tools gain
# ``Depends(get_current_user|get_current_superuser)`` on the handler
# signature; the 11th (``add_canary_tokens``) is exempted via the
# documented ``_PUBLIC_ROUTE_JUSTIFICATION`` bypass because honeypots
# are public BY DESIGN (adding auth would defeat the trap). Per-tool
# fix table:
#
#   add_api_deprecation         GET  /deprecations         current_user
#   add_api_replay_debugger     GET  /debug/requests       superuser (sig)
#                               POST /debug/replay/{id}    superuser (sig)
#                               DELETE /debug/flush        superuser (sig)
#   add_canary_tokens           (3 honeypots)              _PUBLIC_ROUTE_JUSTIFICATION
#   add_cedar_policies          POST /authz/check          superuser
#                               GET  /authz/policies       superuser
#   add_cors_config             GET  /cors/config          superuser
#   add_dependency_health_map   GET  /health/map           superuser
#                               GET  /health/map.html      superuser
#   add_health_deep             GET  /health/deep          superuser (/live + /ready stay public)
#   add_long_running_task       POST /tasks                current_user
#                               GET  /tasks/{wid}          current_user
#                               DELETE /tasks/{wid}        current_user
#   add_opa_integration         POST /authz/opa/check      superuser
#                               GET  /authz/opa/health     superuser
#   add_scheduled_tasks         GET  /scheduler/jobs       superuser
#
# Verified by ``engine/tests/test_w2_batch_b011_all_admin_closed.py``.
#
# Phase A1 (2026-05-31, engine/b011-scope-expand) — scope + regex expansion
# (#118 + #120) revealed 17 new routes across 7 units. Each gets a waiver
# citing the GH issue that owns the fix. The waiver set now includes BOTH
# template tool names (snake_case ``add_*``) AND adapter file stems
# (``*Adapter`` PascalCase); the two namespaces don't collide.
#
#   add_compliance_engine        → RESOLVED R8-J8-1 (superuser-gated, un-waived)
#   add_outbox_pattern           → #131 (DLQ admin + stub data)
#   add_stripe_refund_flow       → #136 (webhook needs verify_stripe_signature dep)
#   add_websocket_presence       → RESOLVED R8-J8-2 (CurrentUser-gated, un-waived)
#   AuditLogAdapter              → #125 (auth + server-side actor + durable ledger)
#   EventSourcedStoreAdapter     → #124 (auth + durable store)
#   SagaAdapter                  → #137 (adapter auth-injection pattern, Phase A2)
# ---------------------------------------------------------------------------
# Waived pending issue #131 — add_outbox_pattern (DLQ admin + real data)
# Waived pending issue #136 — add_stripe_refund_flow (webhook needs signature verify dep)
# RESOLVED (R5-S1-F1/F2) — AuditLogAdapter now superuser-gates every route and
# records the actor from the authenticated principal; un-waived so the rule
# enforces it.
# RESOLVED (R5-O2-D6) — EventSourcedStoreAdapter now requires an injected auth
# dependency on every /events route; un-waived so the rule enforces it.
# RESOLVED (R8-J8-1, CRITICAL) — add_compliance_engine now gates every route
# (erasure / SOC2 evidence / Article 30 / status) with ``CurrentSuperuser``;
# un-waived so the rule enforces the GDPR erasure auth that #135 deferred.
# RESOLVED (R8-J8-2, HIGH) — add_websocket_presence now requires ``CurrentUser``
# on both REST companion routes (GET /presence/online enumerated every online
# user's UUID; GET /presence/{user_id} leaked any user's status/last_seen/device);
# un-waived so the rule enforces auth on the presence polling surface.
# Waived pending issue #137 — SagaAdapter (adapter auth-injection pattern)
_WAIVED_TOOLS: frozenset[str] = frozenset(
    {
        "add_outbox_pattern",
        "add_stripe_refund_flow",
        "SagaAdapter",
    }
)

# Per-spec regex — admin / diagnostic / cross-tenant path segments.
#
# Phase A1 (#120) expansion: added ``outbox``, ``compliance``, ``refunds``,
# ``presence``, ``webhook``, ``websocket``, ``notif`` — these all carry
# admin-grade side-effects (DLQ inspection, GDPR erasure, payment refunds,
# user presence enumeration, signed event ingress, push fan-out) and were
# previously invisible to the regex. ``notif`` is a prefix so it also
# catches the existing ``notifications`` keyword as a substring; both are
# kept explicit for grep-ability.
_ADMIN_PATH_RE = re.compile(
    r"^(/api/v\d+)?/("
    r"admin|debug|scheduler|tasks|deprecations|authz|storage|"
    r"health/(deep|map)|cors/config|events|event-store|audit-logs|"
    r"notifications|versions|throttle/status|metrics-admin|secrets|migrate|"
    r"outbox|compliance|refunds|presence|webhook|websocket|notif"
    r")"
)

# Verbs that mount HTTP handlers on an APIRouter.
_HTTP_VERBS: frozenset[str] = frozenset({"get", "post", "put", "patch", "delete"})

# Parameter-name tokens that satisfy "has auth" at the handler signature.
_AUTH_PARAM_TOKENS: frozenset[str] = frozenset({"current_user", "superuser", "principal"})

# A Depends(...) target name that satisfies "has auth".
_AUTH_DEPENDS_RE = re.compile(r"^(get_current_|require_|verify_).+")

# Templates we scan. Use a tuple so each file is visited once (a single
# template like ``cedar_routes.py.tmpl`` matches both ``*route*`` and
# ``*routes*``; we dedupe via a set below).
_TEMPLATE_GLOBS: tuple[str, ...] = (
    "**/templates/*route*.py.tmpl",
    "**/templates/*routes*.py.tmpl",
)

# Adapter modules (Phase A1, #118). Plain Python under
# ``core/venous/_adapters/fastapi/`` mount the same kind of admin routes
# the template scan was designed to catch but were previously invisible
# because the rule only globbed templates. We scan every ``*.py`` in the
# adapter dir and exclude ``__init__.py`` + ``_test_*``/``test_*`` per
# spec. Sub-packages are not currently used; if added, ``rglob`` may be
# needed.
_ADAPTER_DIR = Path("core/venous/_adapters/fastapi")


def _is_scannable_adapter(path: Path) -> bool:
    """True if *path* is an adapter module (not a test, init, or pycache)."""
    name = path.name
    if name == "__init__.py":
        return False
    if name.startswith("_test_") or name.startswith("test_"):
        return False
    if "__pycache__" in path.parts:
        return False
    return path.suffix == ".py"


def _string_default_for_param(fn: ast.FunctionDef | ast.AsyncFunctionDef, param: str) -> str | None:
    """Return the string-literal default for parameter *param* of *fn*, or
    ``None`` if no such default exists.

    Required by the adapter scope (Phase A1, #118): adapter ``install``
    functions declare ``prefix: str = "/events"`` as a kwarg and then write
    ``router = APIRouter(prefix=prefix)``. Without this resolver the
    rule would see ``prefix=<Name>`` and treat the prefix as empty,
    causing ``/events/{aggregate_id}`` to look like ``/{aggregate_id}``
    which trivially fails the admin-path regex.

    We only resolve string-literal defaults; anything dynamic stays
    unresolved (the rule errs on the side of "no prefix" rather than
    guessing).
    """
    args = fn.args
    # Map each arg (positional + kwonly) to its default expr, if any.
    pos_args = list(args.posonlyargs) + list(args.args)
    pos_defaults = list(args.defaults)
    # ``defaults`` aligns with the TAIL of pos_args.
    if pos_defaults:
        offset = len(pos_args) - len(pos_defaults)
        for i, d in enumerate(pos_defaults):
            a = pos_args[offset + i]
            if a.arg == param and isinstance(d, ast.Constant) and isinstance(d.value, str):
                return d.value
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if d is None:
            continue
        if a.arg == param and isinstance(d, ast.Constant) and isinstance(d.value, str):
            return d.value
    return None


def _enclosing_function(
    tree: ast.AST, target: ast.AST
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the innermost FunctionDef/AsyncFunctionDef containing *target*,
    or ``None`` if *target* lives at module scope.

    Builds a child→parent map by walking *tree* once, then walks upward
    from *target*. O(n) over the tree; the recursive variant earlier
    revision had quadratic worst case.
    """
    parent_of: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_of[id(child)] = parent
    cur = parent_of.get(id(target))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parent_of.get(id(cur))
    return None


def _extract_router_prefix(tree: ast.AST) -> str:
    """Return the ``prefix=`` kwarg of the module's ``router = APIRouter(...)``.

    Returns ``""`` if no prefix is declared, multiple routers are present,
    or the prefix cannot be resolved to a string literal (we can't reason
    about dynamic prefixes — treat as empty rather than crash).

    Resolution rules (in order):
      1. ``prefix=<str literal>`` → return literal.
      2. ``prefix=<Name>`` where ``<Name>`` is a parameter of the
         enclosing function with a string-literal default → return default.
         This catches the adapter ``install(..., prefix: str = "/X")``
         pattern that Phase A1 (#118) added to scope.
      3. Anything else → return ``""``.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg != "prefix":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
            if isinstance(kw.value, ast.Name):
                fn = _enclosing_function(tree, node)
                if fn is not None:
                    resolved = _string_default_for_param(fn, kw.value.id)
                    if resolved is not None:
                        return resolved
            return ""
        return ""
    return ""


def _decorator_path_and_verb(dec: ast.AST) -> tuple[str, str] | None:
    """Return ``(verb, path)`` if ``dec`` is ``@router.<verb>(path, ...)``.

    Accepts both positional ``@router.get("/x")`` and keyword
    ``@router.get(path="/x")`` forms. Returns ``None`` for any decorator
    that isn't a recognised HTTP verb on an attribute call, or whose path
    isn't a string literal (dynamic paths are out of scope for the
    static AST check).
    """
    if not isinstance(dec, ast.Call):
        return None
    fn = dec.func
    if not isinstance(fn, ast.Attribute) or fn.attr not in _HTTP_VERBS:
        return None
    # Positional path
    if dec.args and isinstance(dec.args[0], ast.Constant):
        val = dec.args[0].value
        if isinstance(val, str):
            return fn.attr, val
    # Keyword path
    for kw in dec.keywords:
        if kw.arg == "path" and isinstance(kw.value, ast.Constant):
            val = kw.value.value
            if isinstance(val, str):
                return fn.attr, val
    return None


def _expr_has_auth_token(expr: ast.AST) -> bool:
    """True if ``expr`` references an auth-bearing name, Security(), or
    Depends(<auth_name>)."""
    for sub in ast.walk(expr):
        # Bare name like ``current_user`` or annotation ``CurrentUser`` etc.
        if isinstance(sub, ast.Name) and (sub.id in _AUTH_PARAM_TOKENS or sub.id == "Security"):
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _AUTH_PARAM_TOKENS:
            return True
        # Calls — Security(...) anywhere, or Depends(<auth_name>).
        if isinstance(sub, ast.Call):
            fn = sub.func
            name: str | None = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name == "Security":
                return True
            if name == "Depends" and sub.args:
                target = sub.args[0]
                if isinstance(target, ast.Name) and _AUTH_DEPENDS_RE.match(target.id):
                    return True
                if isinstance(target, ast.Attribute) and _AUTH_DEPENDS_RE.match(target.attr):
                    return True
    return False


def _handler_has_auth(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True iff the handler signature carries any auth token / dep."""
    args = node.args
    for arg in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
        if arg.arg in _AUTH_PARAM_TOKENS:
            return True
        if arg.annotation is not None and _expr_has_auth_token(arg.annotation):
            return True
    for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
        if _expr_has_auth_token(default):
            return True
    return False


def _file_has_public_justification(tree: ast.Module) -> bool:
    """True iff the template declares a module-level
    ``_PUBLIC_ROUTE_JUSTIFICATION`` constant (annotated or plain)."""
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_PUBLIC_ROUTE_JUSTIFICATION"
        ):
            return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "_PUBLIC_ROUTE_JUSTIFICATION":
                    return True
    return False


def _tool_name_for_template(path: Path) -> str:
    """Extract the leaf tool directory name from a template path.

    Templates live at ``adapt/extend/<concern>/<tool>/templates/<x>.py.tmpl``.
    The tool name is ``path.parents[1].name``. Falls back to ``"?"`` if the
    layout doesn't match.
    """
    try:
        if path.parent.name == "templates":
            return path.parents[1].name
    except IndexError:
        pass
    return "?"


def _iter_admin_violations(tree: ast.Module, prefix: str) -> list[tuple[str, str, str]]:
    """Yield (verb, effective_path, handler_name) tuples for every
    admin-path route in ``tree`` whose handler lacks auth."""
    out: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            res = _decorator_path_and_verb(dec)
            if res is None:
                continue
            verb, path = res
            sep = "" if path.startswith("/") else "/"
            effective = f"{prefix}{sep}{path}".replace("//", "/")
            if not _ADMIN_PATH_RE.match(effective):
                continue
            if _handler_has_auth(node):
                continue
            out.append((verb.upper(), effective, node.name))
    return out


def _scan_templates(adapt_root: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Return ``{tool_name: [(verb, path, handler), ...]}`` for every
    NON-waived template whose admin routes lack auth."""
    seen: set[Path] = set()
    for pat in _TEMPLATE_GLOBS:
        seen.update(adapt_root.glob(pat))

    out: dict[str, list[tuple[str, str, str]]] = {}
    for tmpl in sorted(seen):
        try:
            src = tmpl.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            # Template isn't valid Python (e.g. uses placeholder tokens
            # that defeat ast.parse). Skip rather than fail — the boot
            # test + template-rendering harness already catches those.
            continue
        if _file_has_public_justification(tree):
            continue
        tool = _tool_name_for_template(tmpl)
        if tool in _WAIVED_TOOLS:
            continue
        prefix = _extract_router_prefix(tree)
        violations = _iter_admin_violations(tree, prefix)
        if violations:
            out.setdefault(tool, []).extend(violations)
    return out


def _scan_adapters(skill_root: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Return ``{adapter_file_stem: [(verb, path, handler), ...]}`` for every
    NON-waived adapter module whose admin routes lack auth.

    Phase A1 (#118): scans ``core/venous/_adapters/fastapi/*.py``,
    excluding ``__init__.py`` + ``_test_*``/``test_*`` per spec. The
    waiver key is the file stem (e.g. ``AuditLogAdapter``) so the
    ``_WAIVED_TOOLS`` set serves as the unified backlog across both
    scopes; clashes between a template tool name and an adapter stem
    are not expected (templates live under ``add_*`` snake_case tools;
    adapters are ``*Adapter`` PascalCase files).
    """
    adapter_root = skill_root / _ADAPTER_DIR
    if not adapter_root.exists():
        return {}
    out: dict[str, list[tuple[str, str, str]]] = {}
    for mod_path in sorted(adapter_root.glob("*.py")):
        if not _is_scannable_adapter(mod_path):
            continue
        try:
            src = mod_path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        if _file_has_public_justification(tree):
            continue
        stem = mod_path.stem
        if stem in _WAIVED_TOOLS:
            continue
        prefix = _extract_router_prefix(tree)
        violations = _iter_admin_violations(tree, prefix)
        if violations:
            out.setdefault(stem, []).extend(violations)
    return out


def _r_admin_routes_require_auth() -> tuple[bool, str]:
    """B0.11 — admin / diagnostic routes require an auth dependency.

    Closes ROUND5_6_TRIAGE §3 P2 (~15 BLOCKER findings).

    Two scopes (Phase A1, #118):
      * Templates under ``adapt/**/templates/*route*.py.tmpl`` /
        ``*routes*.py.tmpl``.
      * Adapter modules under ``core/venous/_adapters/fastapi/*.py``
        (excluding ``__init__.py`` + ``_test_*``/``test_*``).

    Returns ``(True, msg)`` when both scopes are clean. Returns
    ``(False, msg)`` listing the first few offending
    ``(scope:identifier, VERB path)`` pairs when a regression slips in.
    """
    adapt_root = SKILL_ROOT / "adapt"
    if not adapt_root.exists():
        return False, f"missing: {adapt_root.relative_to(SKILL_ROOT)}"

    tmpl_offenders = _scan_templates(adapt_root)
    adapter_offenders = _scan_adapters(SKILL_ROOT)
    total_offenders_count = len(tmpl_offenders) + len(adapter_offenders)
    if not tmpl_offenders and not adapter_offenders:
        return True, (
            f"§B0.11 satisfied: 0 unwaived admin-route auth violations "
            f"(templates + adapters; {len(_WAIVED_TOOLS)} unit(s) in waiver set)"
        )

    flat: list[str] = []
    for tool, rows in tmpl_offenders.items():
        for verb, path, _fn in rows:
            flat.append(f"template:{tool}: {verb} {path}")
    for stem, rows in adapter_offenders.items():
        for verb, path, _fn in rows:
            flat.append(f"adapter:{stem}: {verb} {path}")
    flat.sort()
    head = flat[:3]
    return False, (
        f"§B0.11 violations: {len(flat)} admin route(s) without auth across "
        f"{total_offenders_count} unit(s): {head}"
        + (f" (+{len(flat) - 3} more)" if len(flat) > 3 else "")
    )
