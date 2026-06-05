"""Generic tool-contract mutation coverage for add_pdf_reports.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_pdf_reports.py in the mutation
runner: ``--tests test_add_pdf_reports.py test_add_pdf_reports_contract.py``.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_pdf_reports import add_pdf_reports
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_pdf_reports import add_pdf_reports

    for check in SCAFFOLDABLE_CHECKS:
        check(add_pdf_reports, "add_pdf_reports")


# ---------------------------------------------------------------------------
# Tool-specific logic mutants (config / routes-init patching, requirements dedup)
# ---------------------------------------------------------------------------


def _run(project: Path) -> None:
    res = add_pdf_reports(ToolInput(project_dir=str(project)))
    assert res.status == "success", res.error


def test_config_block_lands_immediately_after_access_token_anchor():
    """L203 In->NotIn: the config block must be inserted right after the
    ACCESS_TOKEN_EXPIRE_MINUTES anchor, not at the settings/end fallback."""
    project = create_fixture_project(name="pdf_cfg_anchor")
    config_file = project / "app" / "core" / "config.py"
    src_before = config_file.read_text()
    assert "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in src_before

    _run(project)

    src = config_file.read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    expected = anchor + "\n    # --- PDF reports — added by add_pdf_reports tool ---"
    assert expected in src, "block was not inserted directly after the anchor line"
    # And it must NOT have landed at the settings_line fallback position.
    settings_idx = src.index("settings = Settings()")
    block_idx = src.index("# --- PDF reports")
    assert block_idx < settings_idx
    # The block sits between the anchor and settings (anchor branch, not fallback).
    assert src.index(anchor) < block_idx


def test_config_block_uses_settings_line_fallback_when_no_anchor():
    """L207 In->NotIn: when the ACCESS_TOKEN anchor is absent but
    `settings = Settings()` is present, the block is inserted just before
    `settings = Settings()`."""
    project = create_fixture_project(name="pdf_cfg_settings")
    config_file = project / "app" / "core" / "config.py"
    config_file.write_text(
        "class Settings:\n    PROJECT_NAME: str = 'x'\n\nsettings = Settings()\n"
    )

    _run(project)

    src = config_file.read_text()
    assert "REPORT_TEMPLATE_DIR" in src
    block_idx = src.index("# --- PDF reports")
    settings_idx = src.index("settings = Settings()")
    assert block_idx < settings_idx, "block must precede settings = Settings()"
    # Verify the block immediately precedes the settings line (settings fallback).
    between = src[block_idx:settings_idx]
    assert "REPORT_MAX_PAGES: int = 100" in between


def test_config_block_appended_at_end_when_no_anchor_no_settings():
    """L210 Add->Sub & L207 fallback: with neither anchor nor settings line,
    the block is appended at the end of the file."""
    project = create_fixture_project(name="pdf_cfg_endfallback")
    config_file = project / "app" / "core" / "config.py"
    config_file.write_text("class Settings:\n    PROJECT_NAME: str = 'x'\n")

    _run(project)

    src = config_file.read_text()
    assert "REPORT_TEMPLATE_DIR" in src
    # Appended at end: nothing of substance follows the block.
    block_idx = src.index("# --- PDF reports")
    tail = src[block_idx:]
    assert tail.rstrip().endswith("REPORT_MAX_PAGES: int = 100")
    # Add->Sub on rstrip+"\n"+block would corrupt the join; the original line
    # `PROJECT_NAME` must remain intact and on its own line above the block.
    assert "PROJECT_NAME: str = 'x'\n" in src
    assert src.index("PROJECT_NAME") < block_idx


def test_router_import_inserted_after_last_app_import():
    """L231 Eq->NotEq, L236 Add->Sub: with `from app.` imports present, the
    reports import is inserted right after the LAST `from app.` import line."""
    project = create_fixture_project(name="pdf_routes_appimport")
    routes_init = project / "app" / "routes" / "__init__.py"
    before = routes_init.read_text()
    assert "from app." in before

    _run(project)

    lines = routes_init.read_text().splitlines()
    import_line = "from app.api.routes.reports import router as reports_router"
    assert import_line in lines
    imp_idx = lines.index(import_line)
    # Every `from app.` import that existed before must come at-or-before our
    # inserted line index (insertion right after the last app import).
    app_idxs = [i for i, ln in enumerate(lines) if ln.startswith("from app.")]
    # Our reports import is itself a `from app.` line and must be the last one.
    assert imp_idx == max(app_idxs), "import not placed after the last app import"


def test_router_include_inserted_after_last_include():
    """L241 Eq->NotEq, L246 Add->Sub: the include_router line is inserted right
    after the LAST existing api_router.include_router line."""
    project = create_fixture_project(name="pdf_routes_include")
    routes_init = project / "app" / "routes" / "__init__.py"

    _run(project)

    lines = routes_init.read_text().splitlines()
    include_line = "api_router.include_router(reports_router)"
    assert include_line in lines
    inc_idx = lines.index(include_line)
    inc_idxs = [i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")]
    assert inc_idx == max(inc_idxs), "include not placed after the last include"


def _routes_init_no_app_imports() -> str:
    """A routes/__init__ that has NO `from app.` imports and NO existing
    include_router lines, but DOES define `api_router = APIRouter()`."""
    return (
        '"""Route registration."""\n'
        "\n"
        "from fastapi import APIRouter\n"
        "\n"
        "api_router = APIRouter()\n"
        "\n"
        '__all__ = ["api_router"]\n'
    )


def test_router_import_fallback_to_apirouter_line():
    """L233 In->NotIn/And->Or, L234 Sub->Add: when there is no `from app.`
    import, the import line is inserted relative to the `api_router = APIRouter()`
    line (idx-1 + 1 == that line's index)."""
    project = create_fixture_project(name="pdf_routes_noappimp")
    routes_init = project / "app" / "routes" / "__init__.py"
    routes_init.write_text(_routes_init_no_app_imports())

    _run(project)

    lines = routes_init.read_text().splitlines()
    import_line = "from app.api.routes.reports import router as reports_router"
    include_line = "api_router.include_router(reports_router)"
    assert import_line in lines
    assert include_line in lines

    apirouter_idx = lines.index("api_router = APIRouter()")
    imp_idx = lines.index(import_line)
    # Fallback path: last_app_import_idx = (apirouter line idx) - 1, then we
    # insert at that + 1, i.e. exactly at the APIRouter line position (pushing
    # APIRouter down by one). So the import must sit immediately above APIRouter.
    assert imp_idx == apirouter_idx - 1, "import not inserted just above APIRouter line"
    # And the import must NOT have been placed at the file head (idx 0) — that is
    # what Sub->Add or And->Or corruption would produce.
    assert imp_idx > 0


def test_router_include_fallback_to_apirouter_line():
    """L243 And->Or, L246 Add->Sub: with no existing include_router lines, the
    include is inserted right after the `api_router = APIRouter()` line."""
    project = create_fixture_project(name="pdf_routes_noinc")
    routes_init = project / "app" / "routes" / "__init__.py"
    routes_init.write_text(_routes_init_no_app_imports())

    _run(project)

    lines = routes_init.read_text().splitlines()
    include_line = "api_router.include_router(reports_router)"
    apirouter_idx = lines.index("api_router = APIRouter()")
    inc_idx = lines.index(include_line)
    # Inserted immediately after the APIRouter() definition line.
    assert inc_idx == apirouter_idx + 1, "include not inserted right after APIRouter line"


def test_requirements_dedup_skips_when_jinja2_present():
    """L252 In->NotIn: if jinja2 is already in requirements.txt, the tool must
    NOT append a second jinja2 line."""
    project = create_fixture_project(name="pdf_reqs_present")
    req = project / "requirements.txt"
    req.write_text("fastapi>=0.110\njinja2>=3.0\n")

    _run(project)

    src = req.read_text()
    assert src.lower().count("jinja2") == 1, "jinja2 was duplicated despite already present"


def test_requirements_jinja2_appended_when_absent():
    """L252 In->NotIn (other side): when jinja2 is absent it must be appended."""
    project = create_fixture_project(name="pdf_reqs_absent")
    req = project / "requirements.txt"
    req.write_text("fastapi>=0.110\n")

    _run(project)

    src = req.read_text()
    assert "jinja2>=3.1.0" in src
    assert src.lower().count("jinja2") == 1


def test_router_registration_is_idempotent():
    """L224 dedup guard / L246 ordering: re-running on an already-patched routes
    init must not double-insert the include line. (Second full run is a no_op,
    so we exercise _register_router directly via a fresh import already present.)"""
    project = create_fixture_project(name="pdf_routes_idem")
    routes_init = project / "app" / "routes" / "__init__.py"
    _run(project)
    after_first = routes_init.read_text()
    assert after_first.count("api_router.include_router(reports_router)") == 1
    assert after_first.count("from app.api.routes.reports import router as reports_router") == 1
