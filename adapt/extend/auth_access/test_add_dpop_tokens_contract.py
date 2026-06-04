"""Generic tool-contract mutation coverage for add_dpop_tokens.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_dpop_tokens.py in the mutation
runner: ``--tests test_add_dpop_tokens.py test_add_dpop_tokens_contract.py``.

The ``test_kill_*`` functions below target this tool's bespoke logic — the
config-block insertion anchor, the routes-init import/include ordering, and the
requirements dedup guard — which the generic preamble checks do not cover.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens

    for check in SCAFFOLDABLE_CHECKS:
        check(add_dpop_tokens, "add_dpop_tokens")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L174-176)
# ---------------------------------------------------------------------------


def test_kill_config_block_lands_right_after_anchor() -> None:
    """The DPoP config block is inserted immediately after the token-expiry anchor.

    Kills L175 ``if anchor in src`` In->NotIn: with NotIn the anchor branch is
    skipped and the block lands before ``settings = Settings()`` instead, so the
    block no longer directly follows the anchor line.
    """
    project_dir = create_fixture_project(name="dpop_c_anchor")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    cfg = (project_dir / "app" / "core" / "config.py").read_text()

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in cfg
    after = cfg.split(anchor, 1)[1]
    # The very next non-empty content after the anchor must be the DPoP block.
    nxt = after.lstrip("\n")
    assert nxt.startswith("    # --- DPoP tokens (RFC 9449)"), (
        f"DPoP block not placed directly after anchor; got: {nxt[:80]!r}"
    )
    # And it must precede the settings instantiation.
    assert cfg.index("DPOP_ENABLED") < cfg.index("settings = Settings()")


def test_kill_config_anchor_block_indented_in_class() -> None:
    """In the anchor branch the injected fields stay inside the class body.

    Kills L176 ordering by asserting DPOP_ENABLED sits between the anchor and the
    settings instantiation with class-body indentation.
    """
    project_dir = create_fixture_project(name="dpop_c_indent")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    cfg = (project_dir / "app" / "core" / "config.py").read_text()
    for line in cfg.splitlines():
        if "DPOP_ENABLED" in line and ":" in line:
            assert line.startswith("    "), f"DPOP_ENABLED not indented: {line!r}"
            break
    else:
        raise AssertionError("DPOP_ENABLED line not found")


# ---------------------------------------------------------------------------
# _patch_config — settings-line fallback branch (L178-180)
# ---------------------------------------------------------------------------


def test_kill_config_settings_line_fallback() -> None:
    """With no anchor present, the block is inserted just before settings = Settings().

    Kills L179 ``if settings_line in src`` In->NotIn (would fall through to the
    end-append branch) and L180 ``block + "\\n\\n" + settings_line`` Add->Sub
    (string subtraction raises TypeError, crashing the tool).
    """
    project_dir = create_fixture_project(name="dpop_c_settings")
    cfg = project_dir / "app" / "core" / "config.py"
    cfg.write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        '    APP_NAME: str = "x"\n\n\n'
        "settings = Settings()\n"
    )
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    out = cfg.read_text()
    # No anchor existed, so the block must precede the settings instantiation.
    assert "DPOP_ENABLED" in out
    assert out.index("DPOP_ENABLED") < out.index("settings = Settings()"), (
        "block must be inserted before settings = Settings() in the fallback"
    )
    # The block must NOT be appended at the very end (that is the L182 branch).
    assert not out.rstrip().endswith("DPOP_CLOCK_SKEW_S: int = 60"), (
        "fallback wrongly appended block at end instead of before settings line"
    )


# ---------------------------------------------------------------------------
# _patch_config — end-append fallback branch (L181-182)
# ---------------------------------------------------------------------------


def test_kill_config_end_append_fallback() -> None:
    """With neither anchor nor settings instantiation, the block is appended at end.

    Kills L182 ``src.rstrip("\\n") + "\\n" + block`` Add->Sub (string subtraction
    raises TypeError). A success status with the block tacked on the end proves
    the concatenation path executed.
    """
    project_dir = create_fixture_project(name="dpop_c_end")
    cfg = project_dir / "app" / "core" / "config.py"
    cfg.write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        '    APP_NAME: str = "x"\n'
    )
    result = add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    out = cfg.read_text()
    assert out.rstrip().endswith("DPOP_CLOCK_SKEW_S: int = 60"), (
        "block must be appended at the end when no anchor/settings line exists"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — happy path ordering (L194-213 with both anchors present)
# ---------------------------------------------------------------------------


def test_kill_routes_import_after_last_app_import() -> None:
    """The dpop_nonce import lands right after the last ``from app.`` import.

    Kills L198 ``== -1`` Eq->NotEq (would take the fallback, mislocating the
    insert) and L203 ``last_app_import_idx + 1`` Add->Sub (off-by-one would place
    the import before, not after, the last app import / on the wrong line).
    """
    project_dir = create_fixture_project(name="dpop_r_import")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()

    import_line = "from app.api.routes.dpop_nonce import router as dpop_nonce_router"
    imp_idx = lines.index(import_line)
    # The line immediately above must itself be a ``from app.`` import (i.e. the
    # new import was placed directly after the existing block, not before it).
    assert lines[imp_idx - 1].startswith("from app."), (
        f"dpop import not placed after last app import; prev line: {lines[imp_idx - 1]!r}"
    )
    # The import must come before the APIRouter() construction.
    router_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    assert imp_idx < router_idx


def test_kill_routes_include_after_last_include() -> None:
    """The include_router call lands right after the last existing include.

    Kills L208 ``== -1`` Eq->NotEq and L213 ``last_include_idx + 1`` Add->Sub:
    the new include must immediately follow another ``include_router`` call.
    """
    project_dir = create_fixture_project(name="dpop_r_include")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()

    include_line = "api_router.include_router(dpop_nonce_router)"
    inc_idx = lines.index(include_line)
    assert lines[inc_idx - 1].startswith("api_router.include_router"), (
        f"dpop include not placed after last include; prev: {lines[inc_idx - 1]!r}"
    )


# ---------------------------------------------------------------------------
# _patch_routes_init — fallback paths (no app imports / no includes present)
# ---------------------------------------------------------------------------


def _bare_routes_project(name: str) -> Path:
    project_dir = create_fixture_project(name=name)
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        'from fastapi import APIRouter\n\napi_router = APIRouter()\n\n__all__ = ["api_router"]\n'
    )
    return project_dir


def test_kill_routes_import_fallback_before_router_ctor() -> None:
    """With no ``from app.`` imports, the import is inserted just before APIRouter().

    Kills L198 Eq->NotEq (fallback would be skipped, breaking the insert),
    L200 ``"api_router" in line and "APIRouter()" in line`` And->Or / In->NotIn
    (the anchor for the fallback), and L201 ``idx - 1`` Sub->Add (off-by-one would
    place the import after the constructor instead of before it).
    """
    project_dir = _bare_routes_project("dpop_r_imp_fb")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()

    import_line = "from app.api.routes.dpop_nonce import router as dpop_nonce_router"
    imp_idx = lines.index(import_line)
    ctor_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    assert imp_idx < ctor_idx, "fallback import must precede the APIRouter() ctor"
    # And it must land on the line directly above the ctor.
    assert imp_idx == ctor_idx - 1, (
        f"fallback import expected directly above ctor; imp={imp_idx} ctor={ctor_idx}"
    )


def test_kill_routes_include_fallback_after_router_ctor() -> None:
    """With no existing includes, the include is inserted just after APIRouter().

    Kills L208 Eq->NotEq, L210 ``"api_router" in line and "APIRouter()" in line``
    And->Or / In->NotIn (the include fallback anchor), and L213 ``+ 1`` Add->Sub.
    """
    project_dir = _bare_routes_project("dpop_r_inc_fb")
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()

    include_line = "api_router.include_router(dpop_nonce_router)"
    inc_idx = lines.index(include_line)
    ctor_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    assert inc_idx == ctor_idx + 1, (
        f"fallback include expected directly below ctor; inc={inc_idx} ctor={ctor_idx}"
    )


# ---------------------------------------------------------------------------
# _patch_requirements — dedup guard (L220)
# ---------------------------------------------------------------------------


def test_kill_requirements_added_when_absent() -> None:
    """PyJWT is appended when neither casing is present.

    Kills L220 ``"PyJWT" in src or "pyjwt" in src.lower()`` In->NotIn (with the
    guard inverted the tool would early-return and never add PyJWT).
    """
    project_dir = create_fixture_project(name="dpop_req_add")
    req = project_dir / "requirements.txt"
    # The fixture ships PyJWT already; strip every pyjwt line so the "absent"
    # branch is actually exercised.
    cleaned = "\n".join(ln for ln in req.read_text().splitlines() if "pyjwt" not in ln.lower())
    req.write_text(cleaned + "\n")
    assert "pyjwt" not in req.read_text().lower(), "failed to strip PyJWT from fixture"
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    out = req.read_text()
    assert "PyJWT>=2.9.0" in out, "PyJWT requirement not added when absent"


def test_kill_requirements_dedup_lowercase() -> None:
    """When a lowercase ``pyjwt`` pin already exists, no second PyJWT is added.

    Kills L220 BoolOp Or->And and the second In->NotIn: with Or->And the guard
    needs BOTH casings to trip, so a lowercase-only pin would slip through and a
    duplicate PyJWT line would be appended.
    """
    project_dir = create_fixture_project(name="dpop_req_dedup")
    req = project_dir / "requirements.txt"
    # Remove the upper-case PyJWT the fixture ships, then pin a lower-case one,
    # so the only existing match is the ``pyjwt`` (lower) clause of the guard.
    cleaned = "\n".join(ln for ln in req.read_text().splitlines() if "pyjwt" not in ln.lower())
    req.write_text(cleaned + "\npyjwt==2.0.0\n")
    before = req.read_text()
    add_dpop_tokens(ToolInput(project_dir=str(project_dir)))
    out = req.read_text()
    assert out == before, "lowercase pyjwt pin should suppress a duplicate add"
    assert out.lower().count("pyjwt") == 1, (
        f"expected exactly one pyjwt entry, found {out.lower().count('pyjwt')}"
    )
