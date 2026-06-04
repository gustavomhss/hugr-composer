"""Generic + tool-specific mutation coverage for add_cors_config.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. The tool-specific tests below target the
branch / string-concat / dedup-guard mutants the generic checks miss,
exercising the module-level patch helpers (``_patch_config``,
``_patch_main``) directly for precise branch coverage.

Run alongside test_add_cors_config.py in the mutation runner:
``--tests test_add_cors_config.py test_add_cors_config_contract.py``.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cors_config import (
    _patch_config,
    _patch_main,
    add_cors_config,
)
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_FIELDS = ("CORS_ALLOWED_ORIGINS", "CORS_ALLOW_CREDENTIALS", "CORS_MAX_AGE")


def test_contract():
    from adapt.extend.infrastructure.add_cors_config import add_cors_config

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cors_config, "add_cors_config")


# ---------------------------------------------------------------------------
# L90: `if not mw_init.exists()` — the middleware package __init__ is created
# and reported as a created file when it does not yet exist. Flipping `not`
# would skip creating __init__.py on a fresh project.
# ---------------------------------------------------------------------------


def _resolved(paths: list[str]) -> set[str]:
    return {str(Path(p).resolve()) for p in paths}


def _bare_project() -> Path:
    """A minimal project (only app/) that lacks a middleware package and
    prereqs, so the tool creates middleware/__init__.py and auto-scaffolds."""
    import tempfile

    base = Path(tempfile.mkdtemp())
    project_dir = base / "bare"
    (project_dir / "app").mkdir(parents=True)
    return project_dir


def test_middleware_init_created_on_fresh_project() -> None:
    project_dir = _bare_project()
    mw_init = project_dir / "app" / "middleware" / "__init__.py"
    assert not mw_init.exists(), "bare project must start without a middleware package"

    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert mw_init.exists(), "middleware __init__.py must be created"
    assert mw_init.read_text() == '"""Middleware package."""\n'
    assert str(mw_init.resolve()) in _resolved(result.files_created), (
        "middleware __init__.py must be reported in files_created"
    )


# ---------------------------------------------------------------------------
# L84: `list(scaffolded or [])` — scaffolded prereq files must be carried
# into files_created. `or`→`and` would drop them and yield [].
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_reported_in_files_created() -> None:
    """A bare project (no config) auto-scaffolds config.py which must appear
    in files_created. `scaffolded or []` -> `and []` drops them."""
    project_dir = _bare_project()

    result = add_cors_config(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    created = result.files_created
    assert any(c.endswith("app/core/config.py") for c in created), (
        f"auto-scaffolded config.py must be in files_created: {created}"
    )


# ---------------------------------------------------------------------------
# _patch_config branches.
# L152: `if "CORS_ALLOWED_ORIGINS" in src: return` — dedup guard.
# ---------------------------------------------------------------------------


def test_patch_config_dedup_guard(tmp_path: Path) -> None:
    cfg = tmp_path / "config.py"
    original = "class Settings:\n    CORS_ALLOWED_ORIGINS: str = 'keep-me'\n"
    cfg.write_text(original)
    _patch_config(cfg)
    assert cfg.read_text() == original, "existing CORS_ALLOWED_ORIGINS must short-circuit"


# L162/L163: anchor branch — fields injected immediately after REDIS_URL.
def test_patch_config_anchor_branch(tmp_path: Path) -> None:
    cfg = tmp_path / "config.py"
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    cfg.write_text("class Settings:\n" + anchor + "\n    OTHER: int = 1\n")
    _patch_config(cfg)
    out = cfg.read_text()
    for f in _FIELDS:
        assert f in out, f"{f} must be injected via anchor branch"
    # Fields must land right after the REDIS_URL anchor (In branch taken).
    assert out.index(anchor) < out.index("CORS_ALLOWED_ORIGINS")
    assert out.index("CORS_ALLOWED_ORIGINS") < out.index("OTHER: int = 1"), (
        "fields must be inserted directly after the REDIS_URL anchor"
    )


# L165/L166/L168: decorator branch — no anchor, but @computed_field present.
def test_patch_config_decorator_branch(tmp_path: Path) -> None:
    cfg = tmp_path / "config.py"
    cfg.write_text(
        "class Settings:\n"
        "    NAME: str = 'x'\n\n"
        "    @computed_field\n"
        "    def derived(self) -> str:\n"
        "        return self.NAME\n"
    )
    _patch_config(cfg)
    out = cfg.read_text()
    for f in _FIELDS:
        assert f in out, f"{f} must be injected via decorator branch"
    # new_fields must be spliced *before* the decorator (string-concat order).
    assert out.index("CORS_ALLOWED_ORIGINS") < out.index("@computed_field"), (
        "fields must be inserted before the @computed_field decorator"
    )


# L172/L173: marker branch — no anchor, no decorator, but `settings = Settings()`.
def test_patch_config_marker_branch(tmp_path: Path) -> None:
    cfg = tmp_path / "config.py"
    cfg.write_text("class Settings:\n    NAME: str = 'x'\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    for f in _FIELDS:
        assert f in out, f"{f} must be injected via marker branch"
    # new_fields must be spliced *before* the `settings = Settings()` marker.
    assert out.index("CORS_ALLOWED_ORIGINS") < out.index("settings = Settings()"), (
        "fields must be inserted before the settings = Settings() marker"
    )


# L175: final else branch — no anchor, no decorator, no marker -> append at end.
def test_patch_config_append_fallback(tmp_path: Path) -> None:
    cfg = tmp_path / "config.py"
    cfg.write_text("class Settings:\n    NAME: str = 'x'\n")
    _patch_config(cfg)
    out = cfg.read_text()
    for f in _FIELDS:
        assert f in out, f"{f} must be appended in the fallback branch"
    # Appended after the original content (Add at end, not replacing it).
    assert out.index("NAME: str = 'x'") < out.index("CORS_ALLOWED_ORIGINS"), (
        "fallback fields must be appended after existing content"
    )
    assert out.endswith("\n")


# ---------------------------------------------------------------------------
# _patch_main branches.
# L182: dedup guard — existing CORSConfigMiddleware short-circuits.
# ---------------------------------------------------------------------------


def test_patch_main_dedup_guard(tmp_path: Path) -> None:
    main = tmp_path / "main.py"
    original = "app.add_middleware(CORSConfigMiddleware)\n"
    main.write_text(original)
    _patch_main(main)
    assert main.read_text() == original, "existing CORSConfigMiddleware must short-circuit"


# L194/L197: FastAPI-import branch — import injected next to existing import.
def test_patch_main_fastapi_import_branch(tmp_path: Path) -> None:
    main = tmp_path / "main.py"
    main.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    _patch_main(main)
    out = main.read_text()
    assert "from app.middleware.cors_config import CORSConfigMiddleware" in out
    assert "app.add_middleware(CORSConfigMiddleware)" in out
    assert "app.include_router(_cors_debug_router)" in out
    # Import must be attached right after the existing FastAPI import.
    assert out.index("from fastapi import FastAPI") < out.index("cors_config import")
    assert out.index("cors_config import") < out.index("app = FastAPI()"), (
        "cors import must be spliced directly after the FastAPI import line"
    )


# L200: else branch — no FastAPI import -> prepend import to source.
def test_patch_main_prepend_branch(tmp_path: Path) -> None:
    main = tmp_path / "main.py"
    main.write_text("x = 1\ny = 2\n")
    _patch_main(main)
    out = main.read_text()
    assert "from app.middleware.cors_config import CORSConfigMiddleware" in out
    # cors_import is prepended (Add): import precedes the original body.
    assert out.index("cors_config import") < out.index("x = 1"), (
        "cors import must be prepended before the original source"
    )
    # L201: middleware snippet appended at the very end after the body.
    assert out.index("x = 1") < out.index("app.add_middleware(CORSConfigMiddleware)")
    assert out.rstrip().endswith("app.include_router(_cors_debug_router)")
