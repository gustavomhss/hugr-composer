"""TOOL-083: add_pdf_reports — add a production-grade PDF generation layer.

Writes a WeasyPrint/Jinja2 rendering pipeline with lazy weasyprint import,
3 built-in HTML templates (invoice, summary, receipt), Pydantic schemas,
and HTTP routes for generation and download.

The tool is idempotent: a second run detects ``ReportEngine`` in
``app/reports/__init__.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_pdf_reports",
    "description": (
        "Add a production-grade PDF report generation layer with WeasyPrint "
        "lazy import, Jinja2 templates, async generation via run_in_executor, "
        "and download routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_pdf_reports",
}


def add_pdf_reports(inp: ToolInput) -> ToolResult:
    """Add a PDF report generation layer to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with status, files_created, files_modified,
        notes, and next_steps.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    reports_init = app_dir / "reports" / "__init__.py"
    if reports_init.exists() and "ReportEngine" in reports_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "ReportEngine already present in app/reports/__init__.py — PDF reports already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/reports/ (engine.py, __init__.py),",
                "         app/reports/templates/ (invoice.html, summary.html, receipt.html),",
                "         app/schemas/report.py, app/api/routes/reports.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    pkg_dir = app_dir / "reports"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "reports_init.py.tmpl", dest=reports_init, substitutions={})
    files_created.append(str(reports_init))

    engine_file = pkg_dir / "engine.py"
    render_to(_HERE, "engine.py.tmpl", dest=engine_file, substitutions={})
    files_created.append(str(engine_file))

    tpl_dir = pkg_dir / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    for html_name in ("invoice", "summary", "receipt"):
        dest = tpl_dir / f"{html_name}.html"
        _write_html_from_tmpl(f"{html_name}.html.tmpl", dest)
        files_created.append(str(dest))

    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "report.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "reports.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "PDF reports layer added: ReportEngine (WeasyPrint lazy import), "
            "Jinja2 HTML templates (invoice, summary, receipt), async generation "
            "via run_in_executor.",
            "Routes: POST /api/v1/reports/generate, GET /api/v1/reports/{id}/download.",
            "Config fields REPORT_TEMPLATE_DIR, REPORT_OUTPUT_DIR, REPORT_MAX_PAGES added.",
        ],
        next_steps=[
            "pip install weasyprint  # install WeasyPrint and its system dependencies",
            "pip install jinja2  # ensure Jinja2 is installed",
            "Set REPORT_OUTPUT_DIR to a writable directory in .env.",
            "Restart the FastAPI app so the /reports/* routes are loaded.",
        ],
        execution_time_ms=_ms(start),
    )


def _write_html_from_tmpl(tmpl_name: str, dest: Path) -> None:
    """Write an HTML template verbatim (no substitution — preserves Jinja2 syntax).

    Args:
        tmpl_name: Template filename under templates/.
        dest: Destination path to write the file to.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = (_HERE / "templates" / tmpl_name).read_text()
    dest.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_pdf_reports_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_pdf_reports_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    src = config_file.read_text()
    if "REPORT_TEMPLATE_DIR" in src:
        return
    block = (
        "\n"
        "    # --- PDF reports — added by add_pdf_reports tool ---\n"
        '    REPORT_TEMPLATE_DIR: str = "app/reports/templates"\n'
        '    REPORT_OUTPUT_DIR: str = "/tmp/reports"\n'
        "    REPORT_MAX_PAGES: int = 100\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    _register_router(
        routes_init,
        import_line="from app.api.routes.reports import router as reports_router",
        include_line="api_router.include_router(reports_router)",
    )


def _register_router(routes_init: Path, *, import_line: str, include_line: str) -> None:
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_requirements(requirements_file: Path) -> None:
    src = requirements_file.read_text()
    if "jinja2" in src.lower():
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "jinja2>=3.1.0\n")


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
