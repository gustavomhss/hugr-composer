"""Regression tests for R5-O4-C5 — passkey registration trusts client user_id.

Finding (juror ``acdd867db23e99170``):
    ``POST /passkeys/register/{begin,complete}`` accepted ``user_id`` from
    the request body and had NO auth dependency. An attacker could submit
    a victim's UUID, complete the registration ceremony with their OWN
    authenticator, and then log in as the victim — full Account Takeover.

Fix:
    * Schemas no longer expose ``user_id`` on Registration{Begin,Complete}Request.
    * Both register routes carry ``Depends(get_current_user)``.
    * The credential owner is taken from ``current_user.id`` server-side.

These tests scan the EMITTED templates (the artefact the tool ships) so
they fail loudly the moment any future edit re-introduces the bug. They
are deliberately AST-based — no fixture project required — so they run in
milliseconds and stay green even when the wider behavior suite is broken.

Run with::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_passkey_auth_r5_o4_c5.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_HERE = Path(__file__).parent
_TEMPLATES = _HERE / "add_passkey_auth" / "templates"
_ROUTES_TMPL = _TEMPLATES / "routes.py.tmpl"
_SCHEMAS_TMPL = _TEMPLATES / "schemas.py.tmpl"

# The two routes that the finding identifies as ATO-prone.
_REGISTER_HANDLERS: frozenset[str] = frozenset({"register_begin", "register_complete"})

# Schemas that the finding identifies — they MUST NOT expose user_id.
_REGISTER_SCHEMAS: frozenset[str] = frozenset(
    {"RegistrationBeginRequest", "RegistrationCompleteRequest"}
)


def _load(path: Path) -> ast.Module:
    """Parse a template file into an AST module."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Locate a top-level function definition by name."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"handler {name!r} missing from {tree}")


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    """Locate a top-level class definition by name."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"schema class {name!r} missing")


def _handler_auth_dep(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return the name passed to ``Depends(get_current_user)`` if any.

    Walks the handler signature for a parameter whose default is
    ``Depends(get_current_user)`` (positional default OR annotation
    default). Returns the parameter name on hit, else ``None``.
    """
    args = fn.args
    params = list(args.args) + list(args.kwonlyargs)
    defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
    for default in defaults:
        if not isinstance(default, ast.Call):
            continue
        fn_node = default.func
        if isinstance(fn_node, ast.Name) and fn_node.id == "Depends":
            if default.args and isinstance(default.args[0], ast.Name):
                if default.args[0].id == "get_current_user":
                    # Find the bound param name (the arg whose default this is).
                    # Best-effort: just confirm presence.
                    for p in params:
                        if p.arg in {"current_user", "principal", "superuser"}:
                            return p.arg
                    return "current_user"
    return None


# ---------------------------------------------------------------------------
# R5-O4-C5 / 01: routes carry Depends(get_current_user)
# ---------------------------------------------------------------------------

def test_register_routes_have_auth_dep() -> None:
    """R5-O4-C5: both /passkeys/register/* routes MUST require auth.

    The fix wires ``Depends(get_current_user)`` into the handler
    signatures so the credential owner can ONLY come from the
    authenticated session.
    """
    tree = _load(_ROUTES_TMPL)
    for name in sorted(_REGISTER_HANDLERS):
        fn = _find_func(tree, name)
        bound = _handler_auth_dep(fn)
        assert bound is not None, (
            f"R5-O4-C5 regression: handler {name!r} in routes.py.tmpl has "
            f"NO ``Depends(get_current_user)`` — attacker can register a "
            f"passkey under a victim's account (ATO)."
        )


# ---------------------------------------------------------------------------
# R5-O4-C5 / 02: schemas don't expose user_id on the wire
# ---------------------------------------------------------------------------

def test_register_schemas_do_not_expose_user_id() -> None:
    """R5-O4-C5: Registration request schemas MUST NOT have a user_id field.

    The credential owner is taken from ``current_user.id`` server-side;
    accepting a client-supplied UUID re-opens the ATO vector even with
    the auth dep in place (attacker authenticates as themselves, submits
    victim's UUID, registers their authenticator on victim's account).
    """
    tree = _load(_SCHEMAS_TMPL)
    for cls_name in sorted(_REGISTER_SCHEMAS):
        cls = _find_class(tree, cls_name)
        field_names = {
            node.target.id
            for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        assert "user_id" not in field_names, (
            f"R5-O4-C5 regression: schema {cls_name!r} still exposes "
            f"``user_id`` — remove it and bind the credential to "
            f"current_user.id server-side."
        )


# ---------------------------------------------------------------------------
# R5-O4-C5 / 03: emitted code uses current_user.id, not body.user_id
# ---------------------------------------------------------------------------

def test_register_routes_use_current_user_not_body_user_id() -> None:
    """R5-O4-C5: handlers MUST reference current_user.id, NEVER body.user_id.

    Belt-and-braces: even if a future edit re-adds ``user_id`` to the
    schema, the source string scan still catches a ``body.user_id``
    reference inside the register handlers and fails loudly.
    """
    src = _ROUTES_TMPL.read_text(encoding="utf-8")
    assert "body.user_id" not in src, (
        "R5-O4-C5 regression: routes.py.tmpl references ``body.user_id`` — "
        "the credential owner must come from current_user.id."
    )
    assert "current_user.id" in src, (
        "R5-O4-C5 regression: routes.py.tmpl does not reference "
        "``current_user.id`` — auth dep is wired but its value isn't used."
    )


# ---------------------------------------------------------------------------
# R5-O4-C5 / 04: imports for get_current_user and User are present
# ---------------------------------------------------------------------------

def test_routes_import_get_current_user_and_user_model() -> None:
    """R5-O4-C5: routes.py.tmpl must import ``get_current_user`` and ``User``."""
    src = _ROUTES_TMPL.read_text(encoding="utf-8")
    assert "from app.api.deps import get_current_user" in src, (
        "routes.py.tmpl missing ``from app.api.deps import get_current_user``"
    )
    assert "from app.models.user import User" in src, (
        "routes.py.tmpl missing ``from app.models.user import User``"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_register_routes_have_auth_dep,
        test_register_schemas_do_not_expose_user_id,
        test_register_routes_use_current_user_not_body_user_id,
        test_routes_import_get_current_user_and_user_model,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
