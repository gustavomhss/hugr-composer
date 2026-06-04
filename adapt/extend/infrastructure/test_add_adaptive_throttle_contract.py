"""Generic tool-contract mutation coverage for add_adaptive_throttle.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_adaptive_throttle.py in the mutation
runner: ``--tests test_add_adaptive_throttle.py test_add_adaptive_throttle_contract.py``.

Below the generic check, tool-specific mutation-killing tests exercise the
two private patch helpers (_patch_config / _patch_main) directly so each
branch (anchor present/absent, FastAPI import present/absent, marker
present/absent) and the mw __init__ guard are pinned. These kill the
operator flips the generic preamble cannot reach.
"""

from pathlib import Path

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_adaptive_throttle import add_adaptive_throttle

    for check in SCAFFOLDABLE_CHECKS:
        check(add_adaptive_throttle, "add_adaptive_throttle")


# ---------------------------------------------------------------------------
# _patch_config — anchor present branch (L184/L185)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_after_anchor(tmp_path: Path) -> None:
    """L184 In->NotIn / L185 Add->Sub: when the ACCESS_TOKEN anchor is present,
    the throttle fields must be injected DIRECTLY after that anchor line, not
    appended at the end of the file.
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_config

    config = tmp_path / "config.py"
    config.write_text(
        "class Settings(BaseSettings):\n"
        "    SECRET_KEY: str = 'x'\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        "    OTHER_FIELD: int = 1\n"
    )
    _patch_config(config)
    out = config.read_text()
    assert "ADAPTIVE_THROTTLE_ENABLED" in out, "fields were not injected"
    anchor_idx = out.index("ACCESS_TOKEN_EXPIRE_MINUTES: int = 30")
    enabled_idx = out.index("ADAPTIVE_THROTTLE_ENABLED")
    other_idx = out.index("OTHER_FIELD")
    # Must land between the anchor and the field that originally followed it —
    # i.e. inserted right after the anchor, not appended to the file tail.
    assert anchor_idx < enabled_idx < other_idx, (
        f"fields not inserted after anchor: anchor={anchor_idx} "
        f"enabled={enabled_idx} other={other_idx}\n{out}"
    )


def test_patch_config_appends_when_no_anchor(tmp_path: Path) -> None:
    """L184 In->NotIn / L187 Add->Sub: when the anchor is absent, the fields
    must be appended to the end of the existing file content (original content
    preserved, fields after it).
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_config

    config = tmp_path / "config.py"
    config.write_text("class Settings(BaseSettings):\n    SECRET_KEY: str = 'x'\n")
    _patch_config(config)
    out = config.read_text()
    assert "SECRET_KEY: str = 'x'" in out, "original content must be preserved"
    assert "ADAPTIVE_THROTTLE_ENABLED" in out, "fields must be appended"
    # Fields come AFTER the original body (append, not prepend). L187 Add->Sub
    # would corrupt the concatenation / drop a field or the trailing newline.
    assert out.index("SECRET_KEY") < out.index("ADAPTIVE_THROTTLE_ENABLED")
    assert "ADAPTIVE_THROTTLE_BEHIND_PROXY: bool = False" in out, (
        "L187: every field through the last (BEHIND_PROXY) must survive the append"
    )
    # The append branch wraps fields with leading + trailing newlines; a flipped
    # operator would mangle the boundary newline before the first field.
    assert "\n    ADAPTIVE_THROTTLE_ENABLED: bool = False\n" in out


def test_patch_config_idempotent(tmp_path: Path) -> None:
    """L163 In->NotIn: a second _patch_config call is a no-op (fields already
    present) — content must be byte-identical to the first patch.
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_config

    config = tmp_path / "config.py"
    config.write_text("    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n")
    _patch_config(config)
    once = config.read_text()
    _patch_config(config)
    twice = config.read_text()
    assert once == twice, "second patch must not re-inject fields"
    assert once.count("ADAPTIVE_THROTTLE_ENABLED") == 1


# ---------------------------------------------------------------------------
# _patch_main — FastAPI import present/absent (L201/L207)
# ---------------------------------------------------------------------------


def test_patch_main_import_after_fastapi_import(tmp_path: Path) -> None:
    """L201 In->NotIn: when `from fastapi import FastAPI` is present, the
    middleware import must be inserted right after it (not prepended at file top).
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_main

    main = tmp_path / "main.py"
    main.write_text('"""app"""\nfrom fastapi import FastAPI\n\napp = FastAPI(title="x")\n')
    _patch_main(main)
    out = main.read_text()
    fastapi_import_idx = out.index("from fastapi import FastAPI")
    mw_import_idx = out.index(
        "from app.middleware.adaptive_throttle import register_adaptive_throttle"
    )
    # Inserted AFTER the fastapi import line (In branch), not before file start.
    assert mw_import_idx > fastapi_import_idx, "middleware import must follow the fastapi import"
    # And it must sit before the app construction.
    assert mw_import_idx < out.index("app = FastAPI(")


def test_patch_main_import_prepended_when_no_fastapi_import(tmp_path: Path) -> None:
    """L201 In->NotIn / L207 Add->Sub: when there is no `from fastapi import
    FastAPI`, the import line is prepended to the file head (import_line + src).
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_main

    main = tmp_path / "main.py"
    main.write_text("ORIGINAL_FIRST_LINE = 1\nSECOND = 2\n")
    _patch_main(main)
    out = main.read_text()
    mw_idx = out.index("from app.middleware.adaptive_throttle import register_adaptive_throttle")
    orig_idx = out.index("ORIGINAL_FIRST_LINE = 1")
    # L207 Add->Sub (import_line + src) would drop the original body or the
    # import; assert both present AND the import precedes the original content.
    assert mw_idx < orig_idx, "import_line must be prepended before original src"
    assert "SECOND = 2" in out, "original body must be preserved"


# ---------------------------------------------------------------------------
# _patch_main — FastAPI() marker present/absent (L210/L223/L225)
# ---------------------------------------------------------------------------


def test_patch_main_registration_after_fastapi_call(tmp_path: Path) -> None:
    """L210 In->NotIn / L223 Add->Sub: with `app = FastAPI(` present, the
    registration call is inserted immediately after the FastAPI(...) close
    paren — BEFORE any code that follows the constructor, not appended at EOF.
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_main

    main = tmp_path / "main.py"
    main.write_text(
        'from fastapi import FastAPI\n\napp = FastAPI(title="x")\n\nTRAILING_SENTINEL = "end"\n'
    )
    _patch_main(main)
    out = main.read_text()
    reg_idx = out.index("register_adaptive_throttle(app)")
    close_paren_idx = out.index('app = FastAPI(title="x")') + len('app = FastAPI(title="x")')
    sentinel_idx = out.index("TRAILING_SENTINEL")
    # Inserted right after the constructor close paren and BEFORE the trailing
    # code. If L210 flips to NotIn, the else branch appends at EOF -> the call
    # lands AFTER the sentinel, failing this assertion.
    assert close_paren_idx < reg_idx < sentinel_idx, (
        f"registration must be spliced after FastAPI() and before trailing "
        f"code: close={close_paren_idx} reg={reg_idx} sentinel={sentinel_idx}\n{out}"
    )


def test_patch_main_balances_nested_parens(tmp_path: Path) -> None:
    """L216/L218/L219/L223: the paren-matcher must find the OUTER close paren
    even with nested calls inside FastAPI(...). Registration lands after the
    full constructor, before trailing code.
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_main

    main = tmp_path / "main.py"
    main.write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI(\n"
        '    title="x",\n'
        "    lifespan=make_lifespan(deps(1, 2)),\n"
        ")\n\n"
        'TRAILING_SENTINEL = "end"\n'
    )
    _patch_main(main)
    out = main.read_text()
    reg_idx = out.index("register_adaptive_throttle(app)")
    sentinel_idx = out.index("TRAILING_SENTINEL")
    # The registration must be after the full constructor but before the trailing
    # sentinel — proving the depth counter matched the OUTER paren, not the
    # inner deps(...) or make_lifespan(...) close.
    assert reg_idx < sentinel_idx, (
        f"nested-paren match failed; reg at {reg_idx} should precede "
        f"sentinel at {sentinel_idx}\n{out}"
    )
    # The spliced call must sit on its own line right after the close paren.
    assert "\nregister_adaptive_throttle(app)\n" in out


def test_patch_main_appends_when_no_fastapi_marker(tmp_path: Path) -> None:
    """L210 In->NotIn / L225 Add->Sub: with no `app = FastAPI(` marker, the
    registration is appended to the end of the file (src.rstrip + call).
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_main

    main = tmp_path / "main.py"
    main.write_text("from fastapi import FastAPI\nHEAD = 1\nBODY_LAST_LINE = 2\n")
    _patch_main(main)
    out = main.read_text()
    reg_idx = out.index("register_adaptive_throttle(app)")
    body_idx = out.index("BODY_LAST_LINE = 2")
    # No marker -> else branch appends at EOF. L225 Add->Sub would drop the body
    # or the call; assert body preserved AND the call appended after it.
    assert body_idx < reg_idx, "registration must be appended after existing body"
    assert "HEAD = 1" in out, "original body must be preserved on append"
    assert out.rstrip().endswith("register_adaptive_throttle(app)"), (
        "registration call must be the final statement when appended"
    )


def test_patch_main_idempotent(tmp_path: Path) -> None:
    """L194 In->NotIn: a second _patch_main call is a no-op — content stays
    byte-identical and the registration appears exactly once.
    """
    from adapt.extend.infrastructure.add_adaptive_throttle import _patch_main

    main = tmp_path / "main.py"
    main.write_text("from fastapi import FastAPI\n\napp = FastAPI()\n")
    _patch_main(main)
    once = main.read_text()
    _patch_main(main)
    twice = main.read_text()
    assert once == twice, "second patch_main must be a no-op"
    assert once.count("register_adaptive_throttle(app)") == 1


# ---------------------------------------------------------------------------
# mw __init__.py guard — L106 (not X -> X)
# ---------------------------------------------------------------------------


def test_middleware_init_created_with_content(tmp_path: Path) -> None:
    """L106 `not X -> X`: the middleware package __init__.py must be CREATED
    (with its docstring) on a fresh project where it does not pre-exist, and be
    reported in files_created. The flipped guard would skip creation entirely.
    """
    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_adaptive_throttle import add_adaptive_throttle
    from tests.common.fixture_factory import create_fixture_project

    project_dir = create_fixture_project(name="at_mwinit")
    mw_init = project_dir / "app" / "middleware" / "__init__.py"
    # Force the not-yet-exists branch: remove the package init (and dir) so the
    # tool must (re)create it. The fixture/orchestrator may pre-seed it.
    if mw_init.parent.exists():
        for child in mw_init.parent.iterdir():
            child.unlink()
        mw_init.parent.rmdir()
    assert not mw_init.exists(), "precondition: mw __init__ must not pre-exist"
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert mw_init.exists(), "L106: middleware __init__.py must be created"
    assert mw_init.read_text() == '"""Middleware package."""\n', (
        "L106: __init__.py must be written with the package docstring"
    )
    # It must be reported in files_created (resolve both sides for macOS symlink).
    created = {str(Path(p).resolve()) for p in result.files_created}
    assert str(mw_init.resolve()) in created, (
        "L106: created __init__.py must appear in files_created"
    )
