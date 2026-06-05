"""Generic tool-contract mutation coverage for add_ml_gpu_inference.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_ml_gpu_inference.py in the mutation
runner: ``--tests test_add_ml_gpu_inference.py test_add_ml_gpu_inference_contract.py``.

The ``test_kill_*`` functions below target this tool's *specific* logic
(config-block placement in ``_patch_config`` and import/include ordering in
``_patch_routes_init``) that the shared preamble checks do not cover.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_ml_gpu_inference import (
    _patch_config,
    _patch_routes_init,
    add_ml_gpu_inference,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_ml_gpu_inference import add_ml_gpu_inference

    for check in SCAFFOLDABLE_CHECKS:
        check(add_ml_gpu_inference, "add_ml_gpu_inference")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line_index(text: str, needle: str) -> int:
    """Return the index of the first line containing *needle* (or -1)."""
    for i, ln in enumerate(text.splitlines()):
        if needle in ln:
            return i
    return -1


def _bare_config(d: Path, body: str) -> Path:
    f = d / "config.py"
    f.write_text(body)
    return f


def _bare_routes(d: Path, body: str) -> Path:
    f = d / "routes_init.py"
    f.write_text(body)
    return f


# ---------------------------------------------------------------------------
# _patch_config — block placement
# ---------------------------------------------------------------------------


def test_kill_config_anchor_placement() -> None:
    """L191/L192 (anchor In->NotIn): the GPU block lands *right after* the
    ACCESS_TOKEN_EXPIRE_MINUTES anchor when that anchor is present.

    If the anchor membership test flips, the tool falls through to the
    settings-line branch and the block lands somewhere else.
    """
    project_dir = create_fixture_project(name="gpu_cfg_anchor")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    content = (project_dir / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in content
    anchor_idx = _line_index(content, anchor)
    block_idx = _line_index(content, "GPU inference settings")
    enabled_idx = _line_index(content, "GPU_ENABLED")
    # Block comment is the very next line after the anchor.
    assert block_idx == anchor_idx + 1, (
        f"GPU block must directly follow the anchor (anchor@{anchor_idx}, block@{block_idx})"
    )
    assert enabled_idx == anchor_idx + 2


def test_kill_config_settings_line_branch() -> None:
    """L196 (settings_line In->NotIn): with NO anchor but a settings line,
    the block is injected *before* ``settings = Settings()``.

    If the membership flips, it falls to the append-at-end branch and the
    block lands after the settings instantiation.
    """
    d = Path(tempfile.mkdtemp())
    cfg = _bare_config(
        d,
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        '    APP_NAME: str = "x"\n'
        "settings = Settings()\n",
    )
    _patch_config(cfg)
    content = cfg.read_text()
    gpu_idx = _line_index(content, "GPU_ENABLED")
    settings_idx = _line_index(content, "settings = Settings()")
    assert gpu_idx != -1 and settings_idx != -1
    assert gpu_idx < settings_idx, (
        "GPU block must precede 'settings = Settings()' when no anchor exists"
    )


def test_kill_config_append_fallback() -> None:
    """L199 (else-branch BinOp Add->Sub): with neither anchor nor settings
    line, the block is *appended* to the source.

    Flipping Add->Sub turns ``src.rstrip() + block`` into a str subtraction
    which raises TypeError, so the patch would crash.
    """
    d = Path(tempfile.mkdtemp())
    cfg = _bare_config(
        d,
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        '    APP_NAME: str = "x"\n',
    )
    _patch_config(cfg)
    content = cfg.read_text()
    assert "GPU_ENABLED" in content
    assert "GPU_MIXED_PRECISION" in content
    # Appended at the end: the GPU block is the last meaningful content.
    assert content.rstrip().endswith("GPU_MIXED_PRECISION: bool = False")


def test_kill_config_idempotent_guard() -> None:
    """L181 (GPU_ENABLED In->NotIn): a second patch is a no-op (no double
    insertion of the block)."""
    d = Path(tempfile.mkdtemp())
    cfg = _bare_config(
        d,
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        '    APP_NAME: str = "x"\n'
        "settings = Settings()\n",
    )
    _patch_config(cfg)
    once = cfg.read_text()
    _patch_config(cfg)
    twice = cfg.read_text()
    assert once == twice
    assert twice.count("GPU_ENABLED") == 1


# ---------------------------------------------------------------------------
# _patch_routes_init — import + include ordering (with from-app lines)
# ---------------------------------------------------------------------------


def test_kill_routes_import_after_last_from_app() -> None:
    """L220 (insert index BinOp Add->Sub): the gpu_status import is inserted
    *immediately after* the last ``from app.`` import.

    If +1 flips to -1, the import lands one line too early (before the last
    from-app import).
    """
    project_dir = create_fixture_project(name="gpu_routes_import")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "routes" / "__init__.py").read_text()
    lines = content.splitlines()
    gpu_import_idx = _line_index(content, "import router as gpu_status_router")
    # The line directly above the gpu import must itself be a from-app import.
    assert gpu_import_idx > 0
    assert lines[gpu_import_idx - 1].startswith("from app."), (
        f"gpu import must follow a from-app line, got prev={lines[gpu_import_idx - 1]!r}"
    )
    # And it must come before the APIRouter() construction line.
    api_idx = _line_index(content, "api_router = APIRouter()")
    assert gpu_import_idx < api_idx


def test_kill_routes_include_after_last_include() -> None:
    """L230 (insert index BinOp Add->Sub): the include is inserted
    *immediately after* the last existing ``api_router.include_router`` call.
    """
    project_dir = create_fixture_project(name="gpu_routes_include")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "routes" / "__init__.py").read_text()
    lines = content.splitlines()
    gpu_inc_idx = _line_index(content, "include_router(gpu_status_router)")
    assert gpu_inc_idx > 0
    assert lines[gpu_inc_idx - 1].startswith("api_router.include_router"), (
        "gpu include must follow another include_router call"
    )


def test_kill_routes_idempotent() -> None:
    """L208 (import_line In->NotIn): a second registration is a no-op."""
    project_dir = create_fixture_project(name="gpu_routes_idem")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    content_once = (project_dir / "app" / "routes" / "__init__.py").read_text()
    # Re-run directly on the routes file.
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    _patch_routes_init(routes_init)
    content_twice = routes_init.read_text()
    assert content_once == content_twice
    assert content_twice.count("gpu_status_router") == 2  # one import + one include


# ---------------------------------------------------------------------------
# _patch_routes_init — fallback path (NO from-app lines, NO includes)
# ---------------------------------------------------------------------------


def _fallback_src() -> str:
    # Earlier line mentions 'api_router' but NOT 'APIRouter()' so a BoolOp
    # And->Or flip (or an In->NotIn flip) would match the wrong line.
    return (
        '"""Route registration."""\n'
        "from fastapi import APIRouter\n"
        "# configure the api_router below\n"
        "api_router = APIRouter()\n"
    )


def test_kill_routes_fallback_import_position() -> None:
    """L215/L217/L218: when there are NO ``from app.`` lines, the import is
    inserted directly *before* the ``api_router = APIRouter()`` line, found
    by the ``"api_router" in ln and "APIRouter()" in ln`` scan.

    - L215 Eq->NotEq: fallback never runs -> import lands at index 0 (top).
    - L217 And->Or / In->NotIn: matches the earlier comment line that has
      'api_router' but not 'APIRouter()' -> import lands before the comment.
    - L218 Sub->Add: insert index shifts -> import lands after APIRouter().
    """
    d = Path(tempfile.mkdtemp())
    f = _bare_routes(d, _fallback_src())
    _patch_routes_init(f)
    content = f.read_text()
    lines = content.splitlines()
    imp_idx = _line_index(content, "import router as gpu_status_router")
    comment_idx = _line_index(content, "# configure the api_router below")
    api_idx = _line_index(content, "api_router = APIRouter()")
    assert imp_idx != -1
    # Not at the very top (kills L215 Eq->NotEq and L217 In->NotIn).
    assert imp_idx > 0
    assert not lines[0].startswith("from app.api.routes.gpu_status")
    # After the comment line (kills L217 And->Or).
    assert imp_idx > comment_idx, "import must come after the api_router comment"
    # Directly before the APIRouter() construction (kills L218 Sub->Add).
    assert imp_idx == api_idx - 1, (
        f"import must be the line right before APIRouter() (imp@{imp_idx}, api@{api_idx})"
    )


def test_kill_routes_fallback_include_position() -> None:
    """L225/L227/L230 fallback: with NO existing includes, the include is
    inserted directly *after* the ``api_router = APIRouter()`` line.

    - L225 Eq->NotEq: fallback never runs -> include lands at top (index 0).
    - L227 And->Or / In->NotIn: matches the comment line that has
      'api_router' but not 'APIRouter()' -> include lands at the wrong spot.
    - L230 Add->Sub: insert index shifts -> include lands before APIRouter().
    """
    d = Path(tempfile.mkdtemp())
    f = _bare_routes(d, _fallback_src())
    _patch_routes_init(f)
    content = f.read_text()
    lines = content.splitlines()
    inc_idx = _line_index(content, "include_router(gpu_status_router)")
    api_idx = _line_index(content, "api_router = APIRouter()")
    assert inc_idx != -1
    assert inc_idx > 0  # not at the top (kills L225 Eq->NotEq)
    # Directly after the APIRouter() construction (kills L227 And->Or and L230 Add->Sub).
    assert inc_idx == api_idx + 1, (
        f"include must be the line right after APIRouter() (inc@{inc_idx}, api@{api_idx})"
    )
    assert lines[inc_idx - 1].strip() == "api_router = APIRouter()"


# ---------------------------------------------------------------------------
# L96 — ml/__init__.py creation guard (UnaryNot not X -> X)
# ---------------------------------------------------------------------------


def test_kill_ml_init_created() -> None:
    """L96 (UnaryNot ``not ml_init.exists()`` -> ``ml_init.exists()``):
    on a fresh project the app/ml/__init__.py file is created and reported.

    If the guard flips, the file is never written (because it does not yet
    exist) and never appears in files_created.
    """
    project_dir = create_fixture_project(name="gpu_ml_init")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    ml_init = project_dir / "app" / "ml" / "__init__.py"
    assert ml_init.exists(), "app/ml/__init__.py must be created on a fresh project"
    assert any(p.endswith("app/ml/__init__.py") for p in result.files_created), (
        "app/ml/__init__.py must be reported in files_created"
    )
