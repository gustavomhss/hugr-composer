"""Unit tests for CONTRACT.md §B0.11 — ``admin_routes_require_auth``.

Each test exercises one path of the rule callback
``_r_admin_routes_require_auth`` in
``engine.audit.contract_rules.r_admin_routes_auth``:

* **red** — a synthetic template with an admin path + no auth dep MUST
  cause the rule to return ``(False, ...)``.
* **green via waiver** — when the violating template's tool is in
  ``_WAIVED_TOOLS`` the rule must pass.
* **green via auth-dep present** — when the handler signature carries
  a ``current_user`` annotation the rule must pass.
* **green via _PUBLIC_ROUTE_JUSTIFICATION** — a file declaring the
  documented bypass marker is exempt even without auth.
* **registry shape** — B0.11 is wired into the central ``RULES`` list.
* **live tree** — the rule passes against the as-shipped repo (the
  waiver set covers every current violator).

The synthetic-template tests build a throwaway ``adapt/extend/<concern>/
<tool>/templates/<name>.py.tmpl`` tree inside ``tmp_path``, monkey-patch
``SKILL_ROOT`` to point at it, and call the rule directly. This keeps the
tests deterministic + independent of the production catalog.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_template(
    root: Path, *, concern: str, tool: str, name: str, body: str
) -> Path:
    """Materialise an ``adapt/extend/<concern>/<tool>/templates/<name>``
    template under ``root`` and return the .tmpl path."""
    tmpl_dir = root / "adapt" / "extend" / concern / tool / "templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    tmpl = tmpl_dir / name
    tmpl.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return tmpl


@pytest.fixture
def fake_skill_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``r_admin_routes_auth.SKILL_ROOT`` at a fresh temp tree.

    Yields the root so tests can populate it with synthetic templates.
    """
    from engine.audit.contract_rules import r_admin_routes_auth as mod

    monkeypatch.setattr(mod, "SKILL_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Red-case tests
# ---------------------------------------------------------------------------


def test_b011_rejects_admin_route_without_auth(fake_skill_root: Path) -> None:
    """A synthetic admin route with no auth dep MUST cause B0.11 to fail."""
    _write_template(
        fake_skill_root,
        concern="infrastructure",
        tool="add_synthetic_widget",  # NOT in waiver set
        name="widget_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            router = APIRouter(prefix="/admin", tags=["admin"])


            @router.post("/purge")
            def purge_everything() -> dict:
                return {"ok": True}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, msg = _r_admin_routes_require_auth()
    assert not ok, f"expected fail, got pass with msg={msg!r}"
    assert "add_synthetic_widget" in msg
    assert "/admin/purge" in msg


def test_b011_rejects_authz_check_without_auth(fake_skill_root: Path) -> None:
    """Catches the canonical ``/authz/check`` violator (Cedar shape)."""
    _write_template(
        fake_skill_root,
        concern="auth_access",
        tool="add_synthetic_authz",
        name="authz_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            router = APIRouter(prefix="/authz", tags=["authz"])


            @router.post("/check")
            def check_authorization(payload: dict) -> dict:
                return {"allowed": True}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, msg = _r_admin_routes_require_auth()
    assert not ok
    assert "/authz/check" in msg


def test_b011_matches_api_v_prefix(fake_skill_root: Path) -> None:
    """``/api/v1/admin/backup`` (canary shape) matches the regex."""
    _write_template(
        fake_skill_root,
        concern="infrastructure",
        tool="add_synthetic_canary",
        name="canary_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            router = APIRouter(prefix="/api/v1", tags=["_canary"])


            @router.get("/admin/backup")
            def honeypot_admin_backup() -> dict:
                return {"status": "ok"}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, msg = _r_admin_routes_require_auth()
    assert not ok
    assert "/api/v1/admin/backup" in msg


# ---------------------------------------------------------------------------
# Green-case tests
# ---------------------------------------------------------------------------


def test_b011_waived_tool_passes(
    fake_skill_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A violating template whose tool dir is in ``_WAIVED_TOOLS`` is
    exempt — the waiver set IS the back-compat escape hatch."""
    from engine.audit.contract_rules import r_admin_routes_auth as mod

    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset({"add_synthetic_waived"}))

    _write_template(
        fake_skill_root,
        concern="infrastructure",
        tool="add_synthetic_waived",
        name="some_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            router = APIRouter(prefix="/admin")


            @router.delete("/wipe")
            def wipe() -> dict:
                return {"ok": True}
        ''',
    )

    ok, msg = mod._r_admin_routes_require_auth()
    assert ok, f"waived tool should pass, got fail: {msg}"


def test_b011_handler_with_current_user_annotation_passes(
    fake_skill_root: Path,
) -> None:
    """``current_user: CurrentUser`` annotation satisfies the auth check."""
    _write_template(
        fake_skill_root,
        concern="auth_access",
        tool="add_synthetic_protected",
        name="protected_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            from app.api.deps import CurrentUser

            router = APIRouter(prefix="/authz", tags=["authz"])


            @router.post("/check")
            def check(payload: dict, current_user: CurrentUser) -> dict:
                return {"allowed": True}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, msg = _r_admin_routes_require_auth()
    assert ok, f"current_user-annotated handler should pass, got: {msg}"


def test_b011_handler_with_depends_require_admin_passes(
    fake_skill_root: Path,
) -> None:
    """``Depends(require_admin)`` (name matches ``^require_.+$``) is auth."""
    _write_template(
        fake_skill_root,
        concern="infrastructure",
        tool="add_synthetic_via_depends",
        name="r.py.tmpl",
        body='''
            from fastapi import APIRouter, Depends

            from app.deps import require_admin

            router = APIRouter(prefix="/admin", tags=["admin"])


            @router.post("/purge")
            def purge(_: bool = Depends(require_admin)) -> dict:
                return {"ok": True}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, _ = _r_admin_routes_require_auth()
    assert ok


def test_b011_handler_with_security_dep_passes(fake_skill_root: Path) -> None:
    """``Security(...)`` anywhere in a default expression satisfies auth."""
    _write_template(
        fake_skill_root,
        concern="infrastructure",
        tool="add_synthetic_security",
        name="r.py.tmpl",
        body='''
            from fastapi import APIRouter, Security

            from app.deps import oauth2_scheme

            router = APIRouter(prefix="/admin", tags=["admin"])


            @router.post("/purge")
            def purge(_: str = Security(oauth2_scheme, scopes=["admin"])) -> dict:
                return {"ok": True}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, _ = _r_admin_routes_require_auth()
    assert ok


def test_b011_public_route_justification_bypasses_file(
    fake_skill_root: Path,
) -> None:
    """``_PUBLIC_ROUTE_JUSTIFICATION`` exempts the whole file (spec'd bypass)."""
    _write_template(
        fake_skill_root,
        concern="infrastructure",
        tool="add_synthetic_honeypot",
        name="honeypot_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            _PUBLIC_ROUTE_JUSTIFICATION: str = (
                "honeypot — MUST be public to trigger canary alerts on access"
            )

            router = APIRouter(prefix="/api/v1", tags=["_canary"])


            @router.get("/admin/backup")
            def honeypot_admin_backup() -> dict:
                return {"status": "ok"}
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, _ = _r_admin_routes_require_auth()
    assert ok


def test_b011_non_admin_path_passes(fake_skill_root: Path) -> None:
    """Routes that don't match the admin-path regex are out of scope."""
    _write_template(
        fake_skill_root,
        concern="crud_data",
        tool="add_synthetic_widget_crud",
        name="widget_routes.py.tmpl",
        body='''
            from fastapi import APIRouter

            router = APIRouter(prefix="/widgets", tags=["widgets"])


            @router.get("/")
            def list_widgets() -> list:
                return []
        ''',
    )

    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, _ = _r_admin_routes_require_auth()
    assert ok


# ---------------------------------------------------------------------------
# Registry + live-tree wiring
# ---------------------------------------------------------------------------


def test_b011_registered_in_central_rules_list() -> None:
    """The rule is wired into the central ``RULES`` list at item ``B0.11``."""
    from engine.audit.contract_rules._registry import RULES

    items = {r.item: r for r in RULES}
    assert "B0.11" in items, "B0.11 missing from central RULES list"
    rule = items["B0.11"]
    assert rule.phase == 0
    assert "admin" in rule.description.lower()


def test_b011_live_tree_is_green() -> None:
    """The rule MUST pass against the as-shipped catalog (waivers cover every
    current violator). Catches regressions where the waiver set drifts out of
    sync with reality (e.g. a Wave-1 fix lands without removing the waiver)."""
    from engine.audit.contract_rules.r_admin_routes_auth import (
        _r_admin_routes_require_auth,
    )

    ok, msg = _r_admin_routes_require_auth()
    assert ok, f"B0.11 must be green on main; got: {msg}"


def test_b011_waiver_set_only_lists_real_violators() -> None:
    """Every entry in ``_WAIVED_TOOLS`` must correspond to a directory that
    EXISTS under ``adapt/extend/`` AND currently triggers the rule when the
    waiver is suspended. Prevents the waiver set from accumulating dead entries
    that hide future regressions."""
    from engine.audit.contract_rules import r_admin_routes_auth as mod
    from engine.audit.contract_rules._common import SKILL_ROOT

    adapt_extend = SKILL_ROOT / "adapt" / "extend"
    missing_dirs: list[str] = []
    for tool in mod._WAIVED_TOOLS:
        if not any(adapt_extend.glob(f"*/{tool}")):
            missing_dirs.append(tool)
    assert not missing_dirs, (
        f"_WAIVED_TOOLS lists tools with no matching adapt/extend dir: "
        f"{missing_dirs}"
    )
