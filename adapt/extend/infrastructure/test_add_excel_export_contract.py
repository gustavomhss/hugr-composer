"""Generic tool-contract mutation coverage for add_excel_export.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_excel_export.py in the mutation
runner: ``--tests test_add_excel_export.py test_add_excel_export_contract.py``.

The ``test_kills_*`` functions below target this tool's bespoke logic
(config-block insertion anchor, router import/include ordering, and the
requirements dedup) — the survivors the generic preamble suite cannot reach.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_excel_export import (
    _patch_config,
    _patch_requirements,
    _register_router,
    add_excel_export,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_excel_export import add_excel_export

    for check in SCAFFOLDABLE_CHECKS:
        check(add_excel_export, "add_excel_export")


# --------------------------------------------------------------------------
# _patch_config — anchor placement (L179 In->NotIn) + idempotency (L170)
# --------------------------------------------------------------------------


def test_config_block_lands_immediately_after_anchor():
    """L179 In->NotIn: when the anchor exists the Excel block MUST be
    spliced right after the anchor line (not appended via a fallback)."""
    d = Path(tempfile.mkdtemp())
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    cfg = d / "config.py"
    cfg.write_text(f"class Settings:\n    {anchor}\n    OTHER: int = 1\n\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "EXCEL_MAX_ROWS: int = 100000" in out
    assert "EXCEL_CHUNK_SIZE: int = 1000" in out
    # Block sits directly after the anchor, before the next field.
    pos_anchor = out.index(anchor)
    pos_block = out.index("EXCEL_MAX_ROWS")
    pos_other = out.index("OTHER: int = 1")
    assert pos_anchor < pos_block < pos_other
    # And immediately after the anchor (only the comment line between).
    after = out[pos_anchor + len(anchor) :]
    assert after.lstrip("\n").startswith(
        "    # --- Excel export — added by add_excel_export tool ---"
    )


def test_config_patch_idempotent_when_already_present():
    """L170 dedup: a config that already has EXCEL_MAX_ROWS is untouched."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    original = (
        "class Settings:\n"
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n"
        "    EXCEL_MAX_ROWS: int = 5\n\n"
        "settings = Settings()\n"
    )
    cfg.write_text(original)
    _patch_config(cfg)
    assert cfg.read_text() == original
    assert cfg.read_text().count("EXCEL_MAX_ROWS") == 1


def test_config_fallback_to_settings_line_when_no_anchor():
    """L183 In->NotIn: no anchor but a ``settings = Settings()`` line
    present -> the block is inserted *before* that line."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    OTHER: int = 1\n\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "EXCEL_MAX_ROWS: int = 100000" in out
    pos_block = out.index("EXCEL_MAX_ROWS")
    pos_settings = out.index("settings = Settings()")
    assert pos_block < pos_settings


def test_config_fallback_append_when_no_anchor_no_settings_line():
    """L186 BinOp Add->Sub: neither anchor nor settings line -> the block
    is appended to the end of the file (string concat, not subtraction)."""
    d = Path(tempfile.mkdtemp())
    cfg = d / "config.py"
    cfg.write_text("class Settings:\n    OTHER: int = 1\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "EXCEL_MAX_ROWS: int = 100000" in out
    # Appended last: nothing meaningful after the block.
    assert out.rstrip().endswith("EXCEL_CHUNK_SIZE: int = 1000")
    assert out.index("OTHER: int = 1") < out.index("EXCEL_MAX_ROWS")


# --------------------------------------------------------------------------
# _register_router — import/include ordering
# --------------------------------------------------------------------------


def _routes_init_with_app_imports(d: Path) -> Path:
    f = d / "routes_init.py"
    f.write_text(
        '"""Route registration."""\n\n'
        "from fastapi import APIRouter\n\n"
        "from app.api.routes.item import router as item_router\n"
        "from app.api.routes.users import router as users_router\n\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(item_router)\n"
        "api_router.include_router(users_router)\n\n"
        '__all__ = ["api_router"]\n'
    )
    return f


IMPORT_LINE = "from app.api.routes.excel_export import router as excel_export_router"
INCLUDE_LINE = "api_router.include_router(excel_export_router)"


def test_router_import_inserted_after_last_app_import():
    """L212 BinOp Add->Sub: the new import is inserted at
    ``last_app_import_idx + 1`` — i.e. directly *after* the last existing
    ``from app.`` import, never before it."""
    d = Path(tempfile.mkdtemp())
    f = _routes_init_with_app_imports(d)
    _register_router(f, import_line=IMPORT_LINE, include_line=INCLUDE_LINE)
    out = f.read_text()
    lines = out.splitlines()
    import_idx = lines.index(IMPORT_LINE)
    last_existing_app_import = max(
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and ln != IMPORT_LINE
    )
    # New import comes right after the last pre-existing app import.
    assert import_idx == last_existing_app_import + 1
    # It precedes the APIRouter() construction.
    assert import_idx < lines.index("api_router = APIRouter()")


def test_router_include_inserted_after_last_include():
    """L222 BinOp Add->Sub: the include line lands at
    ``last_include_idx + 1`` — after the last existing include_router call."""
    d = Path(tempfile.mkdtemp())
    f = _routes_init_with_app_imports(d)
    _register_router(f, import_line=IMPORT_LINE, include_line=INCLUDE_LINE)
    lines = f.read_text().splitlines()
    include_idx = lines.index(INCLUDE_LINE)
    last_existing_include = max(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and ln != INCLUDE_LINE
    )
    assert include_idx == last_existing_include + 1
    # Include comes after the import.
    assert lines.index(IMPORT_LINE) < include_idx


def test_register_router_idempotent():
    """L200 dedup: re-registering the same import is a no-op."""
    d = Path(tempfile.mkdtemp())
    f = _routes_init_with_app_imports(d)
    _register_router(f, import_line=IMPORT_LINE, include_line=INCLUDE_LINE)
    once = f.read_text()
    _register_router(f, import_line=IMPORT_LINE, include_line=INCLUDE_LINE)
    twice = f.read_text()
    assert once == twice
    assert twice.count(IMPORT_LINE) == 1
    assert twice.count(INCLUDE_LINE) == 1


def test_router_no_app_imports_inserts_before_apirouter():
    """L207 Eq->NotEq + L209 (BoolOp And->Or, In->NotIn) + L210 Sub->Add:
    when there is no ``from app.`` import, the import falls back to the
    ``api_router = APIRouter()`` line and is inserted *before* it
    (idx - 1, +1 => at the APIRouter line position)."""
    d = Path(tempfile.mkdtemp())
    f = d / "routes_init.py"
    f.write_text(
        "from fastapi import APIRouter\n\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(other_router)\n"
    )
    _register_router(f, import_line=IMPORT_LINE, include_line=INCLUDE_LINE)
    lines = f.read_text().splitlines()
    import_idx = lines.index(IMPORT_LINE)
    apirouter_idx = lines.index("api_router = APIRouter()")
    # No app imports => import is placed just before the APIRouter line.
    assert import_idx == apirouter_idx - 1
    # L209 BoolOp And->Or guard: the "from fastapi import APIRouter" line
    # contains "APIRouter()"? No — it does NOT contain the call form, so
    # an Or-flip would mis-anchor onto the wrong line. Confirm the import
    # is NOT placed at the top (which an Or-flip would do).
    assert import_idx != 0


def test_router_include_fallback_when_no_existing_include():
    """L217 Eq->NotEq + L219 (BoolOp And->Or, In->NotIn): with no existing
    ``api_router.include_router`` line, the include falls back to the
    ``api_router = APIRouter()`` anchor and is inserted right after it."""
    d = Path(tempfile.mkdtemp())
    f = d / "routes_init.py"
    f.write_text(
        "from fastapi import APIRouter\n\n"
        "from app.api.routes.item import router as item_router\n\n"
        "api_router = APIRouter()\n"
    )
    _register_router(f, import_line=IMPORT_LINE, include_line=INCLUDE_LINE)
    lines = f.read_text().splitlines()
    include_idx = lines.index(INCLUDE_LINE)
    apirouter_idx = lines.index("api_router = APIRouter()")
    # Include goes immediately after the APIRouter() construction.
    assert include_idx == apirouter_idx + 1


# --------------------------------------------------------------------------
# _patch_requirements — dedup (L228 In->NotIn)
# --------------------------------------------------------------------------


def test_requirements_appends_openpyxl_when_absent():
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    req.write_text("fastapi>=0.115.0\n")
    _patch_requirements(req)
    out = req.read_text()
    assert "openpyxl>=3.1.0" in out
    assert out.count("openpyxl") == 1


def test_requirements_dedup_idempotent_case_insensitive():
    """L228 In->NotIn (.lower() dedup): an existing openpyxl pin — even in
    a different case — blocks a second append."""
    d = Path(tempfile.mkdtemp())
    req = d / "requirements.txt"
    req.write_text("fastapi>=0.115.0\nOpenPyXL==3.0.0\n")
    _patch_requirements(req)
    out = req.read_text()
    # No second pin appended.
    assert out.count("openpyxl>=3.1.0") == 0
    assert out.lower().count("openpyxl") == 1


# --------------------------------------------------------------------------
# End-to-end ordering through the public tool (defence in depth)
# --------------------------------------------------------------------------


def test_full_run_registers_router_in_order():
    d = create_fixture_project(tempfile.mkdtemp())
    result = add_excel_export(ToolInput(project_dir=str(d)))
    assert result.status == "success"
    out = (Path(d) / "app" / "routes" / "__init__.py").read_text()
    lines = out.splitlines()
    assert IMPORT_LINE in lines
    assert INCLUDE_LINE in lines
    # Import precedes the include.
    assert lines.index(IMPORT_LINE) < lines.index(INCLUDE_LINE)
    # Excel import is the last app import (inserted after the others).
    app_imports = [i for i, ln in enumerate(lines) if ln.startswith("from app.")]
    assert lines.index(IMPORT_LINE) == max(app_imports)
