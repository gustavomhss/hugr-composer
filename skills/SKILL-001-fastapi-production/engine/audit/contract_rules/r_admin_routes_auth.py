"""CONTRACT.md §B0.11 — admin/diagnostic routes require auth.

CONTRACT.md scope: §B0.11 ``admin_routes_require_auth`` — AST-scan every
``*route*.py.tmpl`` / ``*routes*.py.tmpl`` under
``skills/SKILL-001-fastapi-production/adapt/`` and REJECT any
``@router.<verb>(...)`` whose effective path (router ``prefix=`` +
decorator ``path``) matches the admin-path regex AND whose handler
signature carries no auth dependency.

Origin: ROUND5_6_TRIAGE §3 P2 — "Admin/diagnostic routes lack
authentication (≥15 occurrences)". Closes ~15 BLOCKER findings.

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
# ---------------------------------------------------------------------------
_WAIVED_TOOLS: frozenset[str] = frozenset(
    {
        # "add_adaptive_throttle" — removed by Wave-2 close-out:
        # /throttle/status now requires get_current_user (R6-O1-F12).
        "add_api_deprecation",
        "add_api_replay_debugger",
        "add_canary_tokens",  # honeypot — needs _PUBLIC_ROUTE_JUSTIFICATION
        "add_cedar_policies",
        "add_cors_config",
        "add_data_versioning",
        "add_dependency_health_map",
        "add_health_deep",
        "add_long_running_task",
        "add_notifications",
        "add_opa_integration",
        # "add_s3_storage" — removed by R6-S6-F1/F5/F6/F7 fix-PR (juror
        # a077cc434dd7a8155): all three /storage routes now require
        # CurrentUser + are prefix-scoped to users/{current_user.id}/.
        "add_scheduled_tasks",
    }
)

# Per-spec regex — admin / diagnostic / cross-tenant path segments.
_ADMIN_PATH_RE = re.compile(
    r"^(/api/v\d+)?/("
    r"admin|debug|scheduler|tasks|deprecations|authz|storage|"
    r"health/(deep|map)|cors/config|events|event-store|audit-logs|"
    r"notifications|versions|throttle/status|metrics-admin|secrets|migrate"
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


def _extract_router_prefix(tree: ast.AST) -> str:
    """Return the ``prefix=`` kwarg of the module's ``router = APIRouter(...)``.

    Returns ``""`` if no prefix is declared, multiple routers are present,
    or the prefix is not a plain string literal (we can't reason about
    dynamic prefixes — treat as empty rather than crash).
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                val = kw.value.value
                if isinstance(val, str):
                    return val
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
        if isinstance(sub, ast.Name):
            if sub.id in _AUTH_PARAM_TOKENS or sub.id == "Security":
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
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_PUBLIC_ROUTE_JUSTIFICATION":
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


def _r_admin_routes_require_auth() -> tuple[bool, str]:
    """B0.11 — admin / diagnostic routes require an auth dependency.

    Closes ROUND5_6_TRIAGE §3 P2 (~15 BLOCKER findings).

    Returns ``(True, msg)`` when every non-waived template under
    ``adapt/`` is clean. Returns ``(False, msg)`` listing the first few
    offending ``(tool, VERB path)`` pairs when a regression slips in.
    """
    adapt_root = SKILL_ROOT / "adapt"
    if not adapt_root.exists():
        return False, f"missing: {adapt_root.relative_to(SKILL_ROOT)}"

    offenders = _scan_templates(adapt_root)
    if not offenders:
        return True, (
            f"§B0.11 satisfied: 0 unwaived admin-route auth violations "
            f"({len(_WAIVED_TOOLS)} tool(s) in waiver set)"
        )

    flat = sorted(
        f"{tool}: {verb} {path}"
        for tool, rows in offenders.items()
        for verb, path, _fn in rows
    )
    head = flat[:3]
    return False, (
        f"§B0.11 violations: {len(flat)} admin route(s) without auth across "
        f"{len(offenders)} tool(s): {head}"
        + (f" (+{len(flat) - 3} more)" if len(flat) > 3 else "")
    )
