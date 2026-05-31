"""Regression tests for W2 BATCH — close all 11 remaining B0.11 waivers.

The B0.11 rule (``r_admin_routes_auth``) AST-scans every
``*route*.py.tmpl`` under ``adapt/`` and rejects any admin /
diagnostic route whose handler signature lacks an auth dependency.
Before this PR the rule had to waive 11 tools (10 templates needing
auth, 1 honeypot module needing the documented public-route bypass).

This test fails LOUDLY if any of those 11 tools regresses in either
of two ways:

1. The tool re-appears in ``_WAIVED_TOOLS`` (someone re-added the
   waiver instead of fixing the template).
2. The fix gets reverted at the template level (the handler signature
   loses its ``Depends(get_current_user|get_current_superuser)``, or
   the honeypot module loses its
   ``_PUBLIC_ROUTE_JUSTIFICATION`` constant).

Per-tool table (route, dep applied):

* add_api_deprecation         GET  /deprecations         current_user
* add_api_replay_debugger     GET  /debug/requests       superuser (sig)
                              POST /debug/replay/{id}    superuser (sig)
                              DELETE /debug/flush        superuser (sig)
* add_canary_tokens           (3 honeypots)              _PUBLIC_ROUTE_JUSTIFICATION
* add_cedar_policies          POST /authz/check          superuser
                              GET  /authz/policies       superuser
* add_cors_config             GET  /cors/config          superuser
* add_dependency_health_map   GET  /health/map           superuser
                              GET  /health/map.html      superuser
* add_health_deep             GET  /health/deep          superuser (/live + /ready stay public)
* add_long_running_task       POST /tasks                current_user
                              GET  /tasks/{wid}          current_user
                              DELETE /tasks/{wid}        current_user
* add_opa_integration         POST /authz/opa/check      superuser
                              GET  /authz/opa/health     superuser
* add_scheduled_tasks         GET  /scheduler/jobs       superuser

DELICATE notes:
  - ``add_health_deep``'s ``/health/live`` and ``/health/ready`` MUST
    stay anonymous (kubelet probes have no credentials). They are
    NOT matched by the B0.11 admin-path regex; if someone tightens
    the regex to match them, this test does NOT catch it — the
    contract_check itself will start failing for non-waived tools.
  - ``add_canary_tokens`` uses the file-level
    ``_PUBLIC_ROUTE_JUSTIFICATION`` bypass on purpose (auth would
    defeat the honeypot trap). Don't add a handler-level auth dep to
    fix a perceived regression — check for the constant instead.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))


# ---------------------------------------------------------------------------
# Per-tool fixture table
# Each row: (tool_name, relative_template_path, expected_dep_kind)
#
# expected_dep_kind:
#   "user"       — signature carries Depends(get_current_user)
#   "superuser"  — signature carries Depends(get_current_superuser)
#   "public"     — file declares _PUBLIC_ROUTE_JUSTIFICATION (honeypot)
# ---------------------------------------------------------------------------
_TOOL_FIXTURES: list[tuple[str, str, str]] = [
    (
        "add_api_deprecation",
        "adapt/extend/api_design/add_api_deprecation/templates/deprecation_route.py.tmpl",
        "user",
    ),
    (
        "add_api_replay_debugger",
        "adapt/extend/infrastructure/add_api_replay_debugger/templates/debug_routes.py.tmpl",
        "superuser",
    ),
    (
        "add_canary_tokens",
        "adapt/extend/infrastructure/add_canary_tokens/templates/canary_honeypot_routes.py.tmpl",
        "public",
    ),
    (
        "add_cedar_policies",
        "adapt/extend/auth_access/add_cedar_policies/templates/authz_routes.py.tmpl",
        "superuser",
    ),
    (
        "add_cors_config",
        "adapt/extend/infrastructure/add_cors_config/templates/cors_debug_route.py.tmpl",
        "superuser",
    ),
    (
        "add_dependency_health_map",
        "adapt/extend/infrastructure/add_dependency_health_map/templates/health_map_routes.py.tmpl",
        "superuser",
    ),
    (
        "add_health_deep",
        "adapt/extend/infrastructure/add_health_deep/templates/health_deep_route.py.tmpl",
        "superuser",
    ),
    (
        "add_long_running_task",
        "adapt/extend/api_design/add_long_running_task/templates/tasks_route.py.tmpl",
        "user",
    ),
    (
        "add_opa_integration",
        "adapt/extend/auth_access/add_opa_integration/templates/opa_routes.py.tmpl",
        "superuser",
    ),
    (
        "add_scheduled_tasks",
        "adapt/extend/infrastructure/add_scheduled_tasks/templates/scheduler_status_route.py.tmpl",
        "superuser",
    ),
]

# 10 templates above + the honeypot fixture above counts as one of those
# 10 — that is the full set the WAIVED list contained at the start of this
# batch PR (11 entries collapsed to 10 templates because the honeypot is
# one tool with three routes covered by a single _PUBLIC_ROUTE_JUSTIFICATION).
# The waiver had 11 *entries* historically; the table reflects the 10
# *files* we needed to touch (canary's three routes share one file).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_HTTP_VERBS: frozenset[str] = frozenset({"get", "post", "put", "patch", "delete"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _signature_has_dep(node: ast.AST, target_name: str) -> bool:
    """True iff ``node`` (a FunctionDef/AsyncFunctionDef) has any param
    whose default is ``Depends(<target_name>)`` (or annotation token)."""
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    args = node.args
    candidates: list[ast.AST] = []
    candidates.extend(d for d in args.defaults)
    candidates.extend(d for d in args.kw_defaults if d is not None)
    # also walk annotations for Annotated[..., Depends(target)]
    for arg in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
        if arg.annotation is not None:
            candidates.append(arg.annotation)
    for expr in candidates:
        for sub in ast.walk(expr):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            name: str | None = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name == "Depends" and sub.args:
                tgt = sub.args[0]
                if isinstance(tgt, ast.Name) and tgt.id == target_name:
                    return True
                if isinstance(tgt, ast.Attribute) and tgt.attr == target_name:
                    return True
    return False


def _iter_route_handlers(tree: ast.Module) -> list[ast.AST]:
    """Yield handler nodes that wear at least one ``@router.<verb>(...)``."""
    out: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if isinstance(fn, ast.Attribute) and fn.attr in _HTTP_VERBS:
                out.append(node)
                break
    return out


def _has_public_justification(tree: ast.Module) -> bool:
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("tool", "rel_template", "kind"), _TOOL_FIXTURES)
def test_tool_not_in_waiver_set(tool: str, rel_template: str, kind: str) -> None:
    """The closed tool MUST NOT re-appear in ``_WAIVED_TOOLS``.

    If this test fails, someone re-added the waiver instead of (or in
    addition to) fixing the template.
    """
    from engine.audit.contract_rules.r_admin_routes_auth import _WAIVED_TOOLS

    assert tool not in _WAIVED_TOOLS, (
        f"{tool!r} was re-added to _WAIVED_TOOLS in r_admin_routes_auth.py; "
        f"the waiver was intentionally removed by the W2 BATCH B0.11 PR. "
        f"If the template regressed, fix the template — do not re-waive."
    )


@pytest.mark.parametrize(("tool", "rel_template", "kind"), _TOOL_FIXTURES)
def test_template_has_expected_auth(tool: str, rel_template: str, kind: str) -> None:
    """Each closed template still carries the expected auth surface.

    * ``kind == "user"`` — at least one route handler binds
      ``Depends(get_current_user)`` in its signature.
    * ``kind == "superuser"`` — at least one route handler binds
      ``Depends(get_current_superuser)`` in its signature.
    * ``kind == "public"`` — the module declares the documented
      ``_PUBLIC_ROUTE_JUSTIFICATION`` bypass constant (honeypots).
    """
    tmpl = SKILL_ROOT / rel_template
    assert tmpl.is_file(), f"template missing: {rel_template}"
    tree = _parse(tmpl)

    if kind == "public":
        assert _has_public_justification(tree), (
            f"{tool}: expected module-level _PUBLIC_ROUTE_JUSTIFICATION "
            f"constant (honeypot bypass) — adding handler-level auth here "
            f"would defeat the canary trap."
        )
        return

    target = "get_current_user" if kind == "user" else "get_current_superuser"
    handlers = _iter_route_handlers(tree)
    assert handlers, f"{tool}: no @router.<verb> handlers found in {rel_template}"

    # Every admin handler in the file should carry the expected dep — but
    # we accept a per-handler split (e.g. add_health_deep keeps /live and
    # /ready public). Assert that AT LEAST ONE handler carries the dep
    # AND that the B0.11 rule itself (which is the source of truth)
    # reports zero violations for this tool — that combined check catches
    # both "fix vanished" and "fix narrowed to a subset that no longer
    # covers the admin paths".
    any_has_dep = any(_signature_has_dep(h, target) for h in handlers)
    assert any_has_dep, (
        f"{tool}: no handler in {rel_template} carries "
        f"Depends({target}). Expected at least one admin route to bind "
        f"the auth dependency in its signature."
    )


def test_b011_rule_reports_zero_violations() -> None:
    """End-to-end: the live B0.11 rule must report zero violations across
    the entire ``adapt/`` tree (and, since Phase A1, ``core/venous/_adapters/
    fastapi/``).

    History:
      * W2 BATCH (2026-05-31): closed every then-known violator and
        drained ``_WAIVED_TOOLS`` to the empty set.
      * Phase A1 (#118 + #120, 2026-05-31): expanded scope to adapters
        and added 7 admin-keyword regex tokens. The expansion revealed
        17 new routes across 7 units (4 templates + 3 adapters), each
        backed by a GH issue and re-added to ``_WAIVED_TOOLS``. The
        post-W2 "set must be empty" invariant is therefore relaxed to
        "every entry MUST cite a tracking issue" — that property is
        enforced by ``test_b011_waiver_set_only_lists_real_violators``
        + manual review of the waiver comment block. This test now
        only asserts the rule is GREEN.
    """
    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, msg = _r_admin_routes_require_auth()
    assert ok, f"§B0.11 reported violations: {msg}"
