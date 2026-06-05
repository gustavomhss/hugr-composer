"""Generic tool-contract mutation coverage for add_ml_model_server.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_ml_model_server.py in the mutation
runner: ``--tests test_add_ml_model_server.py test_add_ml_model_server_contract.py``.

The hand-written ``test_*`` functions below target the tool-specific survivors
in the three patch helpers (``_patch_config``, ``_patch_routes_init``,
``_patch_main``): exact insertion ordering, anchor-vs-fallback branch
selection, and the lifespan ``yield`` / idempotency guards.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_ml_model_server import (
    _patch_config,
    _patch_main,
    _patch_routes_init,
    add_ml_model_server,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_ml_model_server import add_ml_model_server

    for check in SCAFFOLDABLE_CHECKS:
        check(add_ml_model_server, "add_ml_model_server")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line_index(lines: list[str], needle: str) -> int:
    for i, ln in enumerate(lines):
        if needle in ln:
            return i
    raise AssertionError(f"{needle!r} not found in:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# _patch_config — anchor branch + ordering (L203, L207, L210)
# ---------------------------------------------------------------------------


def test_config_block_lands_immediately_after_anchor() -> None:
    """L203 In->NotIn: with the ACCESS_TOKEN anchor present, the ML block is
    inserted directly after that anchor line (not via the settings fallback)."""
    project_dir = create_fixture_project(name="ml_cfg_anchor")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "core" / "config.py").read_text().splitlines()
    anchor_idx = _line_index(lines, "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30")
    # The very next non-empty line must be the ML comment/field block.
    following = "\n".join(lines[anchor_idx + 1 : anchor_idx + 6])
    assert "added by add_ml_model_server tool" in following, (
        f"ML block not directly after anchor:\n{following}"
    )
    assert "ML_MODEL_DIR" in following, "ML_MODEL_DIR not in block right after anchor"


def test_config_fallback_settings_line_branch() -> None:
    """L207 In->NotIn + L208 ordering: with NO anchor but a ``settings =
    Settings()`` line, the block is inserted BEFORE that line (so the
    Settings class still references the fields)."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    PROJECT_NAME: str = 'x'\n\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "ML_MODEL_DIR" in out, "fallback branch did not inject ML_MODEL_DIR"
    lines = out.splitlines()
    block_idx = _line_index(lines, "ML_MODEL_DIR")
    settings_idx = _line_index(lines, "settings = Settings()")
    assert block_idx < settings_idx, (
        "ML block must precede `settings = Settings()` in fallback branch"
    )


def test_config_fallback_append_when_no_anchor_no_settings() -> None:
    """L210 BinOp/concat fallback: no anchor and no settings line -> the block
    is appended to the end of the file."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("X = 1\nY = 2\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "ML_MODEL_DIR" in out, "append fallback did not inject ML_MODEL_DIR"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # Original content must still come first; ML block appended after.
    assert lines[0] == "X = 1" and lines[1] == "Y = 2", (
        f"original content not preserved at top: {lines[:2]}"
    )
    assert any("ML_MODEL_DIR" in ln for ln in lines[2:]), "ML block not appended at end"


def test_config_idempotent_no_double_block() -> None:
    """Second _patch_config is a no-op (guard on ML_MODEL_DIR already present)."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("settings = Settings()\n")
    _patch_config(cfg)
    _patch_config(cfg)
    assert cfg.read_text().count("ML_MODEL_DIR") == 1, "ML block inserted twice"


# ---------------------------------------------------------------------------
# _patch_routes_init — import/include ordering + fallbacks (L222-238)
# ---------------------------------------------------------------------------


def test_routes_import_after_last_from_app() -> None:
    """L228 BinOp Add->Sub: the ml import is inserted right AFTER the last
    ``from app.`` line, not before it."""
    project_dir = create_fixture_project(name="ml_routes_ord")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    ml_import_idx = _line_index(lines, "from app.api.routes.ml import router as ml_router")
    # Every other `from app.` import precedes the ml import (it is appended last).
    other_from_app = [
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and i != ml_import_idx
    ]
    assert other_from_app, "expected pre-existing from-app imports"
    assert ml_import_idx > max(other_from_app), (
        "ml import must come after the last existing from-app import"
    )


def test_routes_include_after_last_include() -> None:
    """L238 BinOp Add->Sub: the include_router(ml_router) call lands right
    after the last existing include_router call."""
    project_dir = create_fixture_project(name="ml_routes_inc")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    ml_inc_idx = _line_index(lines, "api_router.include_router(ml_router)")
    other_inc = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and i != ml_inc_idx
    ]
    assert other_inc, "expected pre-existing include_router calls"
    assert ml_inc_idx > max(other_inc), (
        "ml include_router must come after the last existing include_router"
    )
    # And the include must come after the import (correct relative order).
    import_idx = _line_index(lines, "from app.api.routes.ml import router as ml_router")
    assert ml_inc_idx > import_idx, "include must follow the import"


def test_routes_fallback_no_from_app_uses_apirouter_anchor() -> None:
    """L223 Eq->NotEq + L225 And->Or: when there is NO ``from app.`` line, the
    import anchors on the ``api_router = APIRouter()`` line (inserted just
    before it)."""
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text(
        "from fastapi import APIRouter\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(other_router)\n"
    )
    _patch_routes_init(ri)
    lines = ri.read_text().splitlines()
    import_idx = _line_index(lines, "from app.api.routes.ml import router as ml_router")
    apirouter_idx = _line_index(lines, "api_router = APIRouter()")
    # Import inserted at (anchor_line - 1) + 1 == anchor line position originally,
    # i.e. it must sit immediately before the APIRouter() definition.
    assert import_idx < apirouter_idx, (
        "fallback import must be placed before api_router = APIRouter()"
    )
    assert "from app.api.routes.ml" in "\n".join(lines), "import not added at all"


def test_routes_fallback_include_anchor() -> None:
    """L233 Eq->NotEq + L235 And->Or: when there is NO existing
    include_router call, the ml include anchors on the APIRouter() line."""
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text("from app.core.x import y\napi_router = APIRouter()\n")
    _patch_routes_init(ri)
    out = ri.read_text()
    assert "api_router.include_router(ml_router)" in out, (
        "include fallback branch did not add the ml include_router call"
    )
    lines = out.splitlines()
    inc_idx = _line_index(lines, "api_router.include_router(ml_router)")
    apirouter_idx = _line_index(lines, "api_router = APIRouter()")
    assert inc_idx > apirouter_idx, "include must come after APIRouter() in fallback"


def test_routes_idempotent_no_double_import() -> None:
    """Second patch is a no-op (guard on import_line already present)."""
    project_dir = create_fixture_project(name="ml_routes_idem")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    ri = project_dir / "app" / "routes" / "__init__.py"
    _patch_routes_init(ri)
    text = ri.read_text()
    assert text.count("from app.api.routes.ml import router as ml_router") == 1
    assert text.count("api_router.include_router(ml_router)") == 1


# ---------------------------------------------------------------------------
# _patch_main — idempotency, no-from-app, ordering, yield guard, return True
# ---------------------------------------------------------------------------


def test_main_already_patched_returns_false_no_change() -> None:
    """L245/L246 BoolLiteral True->False: when the ``ml_model_server`` marker
    already exists, _patch_main returns False and writes nothing."""
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    original = "from app.core.config import settings  # ml_model_server\n    yield\n"
    mf.write_text(original)
    changed = _patch_main(mf)
    assert changed is False, "expected no-op (False) when already patched"
    assert mf.read_text() == original, "already-patched main must be untouched"


def test_main_no_from_app_returns_false() -> None:
    """L249/L250 BoolLiteral: with no ``from app.`` line there is no safe
    anchor, so _patch_main returns False and leaves the file alone."""
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    original = "from fastapi import FastAPI\napp = FastAPI()\n"
    mf.write_text(original)
    changed = _patch_main(mf)
    assert changed is False, "expected False when no from-app anchor exists"
    assert "get_registry" not in mf.read_text(), "must not patch without anchor"


def test_main_import_after_last_from_app_and_returns_true() -> None:
    """L252 BinOp Add->Sub + L263 BoolLiteral True->False: import is inserted
    after the last ``from app.`` line and the function reports True."""
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    mf.write_text(
        "from fastapi import FastAPI\n"
        "from app.core.config import settings\n"
        "from app.routes import api_router\n"
        "\n"
        "@asynccontextmanager\n"
        "async def lifespan(app):\n"
        "    await init_db()\n"
        "    yield\n"
    )
    changed = _patch_main(mf)
    assert changed is True, "patch should report True on success"
    lines = mf.read_text().splitlines()
    import_idx = _line_index(lines, "from app.ml.registry import get_registry")
    other_from_app = [
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and i != import_idx
    ]
    assert other_from_app and import_idx > max(other_from_app), (
        "get_registry import must follow the last existing from-app import"
    )


def test_main_get_registry_inserted_before_yield() -> None:
    """L256 NotEq->Eq: when a ``yield`` line exists, the ``get_registry()``
    startup call is inserted immediately before it (the != -1 branch fires)."""
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    mf.write_text(
        "from app.core.config import settings\n"
        "@asynccontextmanager\n"
        "async def lifespan(app):\n"
        "    await init_db()\n"
        "    yield\n"
        "    await shutdown()\n"
    )
    _patch_main(mf)
    lines = mf.read_text().splitlines()
    call_idx = _line_index(lines, "get_registry()  # ML registry initialised")
    yield_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "yield")
    assert call_idx == yield_idx - 1, (
        "get_registry() startup call must be the line directly before yield"
    )
    # And the inserted call must carry the lifespan body indentation (4 spaces).
    assert lines[call_idx].startswith("    get_registry()"), (
        f"call not indented into lifespan body: {lines[call_idx]!r}"
    )


def test_main_no_yield_still_adds_import_only() -> None:
    """L256 NotEq->Eq companion: with no ``yield`` the call is NOT inserted,
    but the import still is (drives the yield_idx == -1 path)."""
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    mf.write_text("from app.core.config import settings\napp = object()\n")
    changed = _patch_main(mf)
    assert changed is True
    out = mf.read_text()
    assert "from app.ml.registry import get_registry" in out, "import must be added"
    assert "get_registry()  # ML registry initialised" not in out, (
        "no yield present -> startup call must not be inserted"
    )


def test_main_listed_in_files_modified() -> None:
    """L263 reaches the caller: a successfully patched main.py is reported in
    result.files_modified."""
    project_dir = create_fixture_project(name="ml_main_mod")
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert any(p.endswith("app/main.py") for p in result.files_modified), (
        f"main.py should be in files_modified: {result.files_modified}"
    )
