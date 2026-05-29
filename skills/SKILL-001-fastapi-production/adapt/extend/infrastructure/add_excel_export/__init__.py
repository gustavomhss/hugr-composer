"""TOOL-084: add_excel_export — add a production-grade Excel export layer.

Writes an OpenPyXL-backed Excel export pipeline with streaming support
for large datasets, an ``ExcelExporter`` class with lazy openpyxl
import, cell formatting and auto-width helpers, HTTP routes for export
generation and download, and a ``StreamingResponse`` for large files.

The tool is idempotent: a second run detects ``ExcelExporter`` in
``app/exports/__init__.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_excel_export",
    "description": (
        "Add a production-grade Excel export layer with OpenPyXL streaming for "
        "large datasets, cell formatting, auto-width columns, and "
        "StreamingResponse download routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_excel_export",
}


def add_excel_export(inp: ToolInput) -> ToolResult:
    """Add an Excel export layer to a FastAPI project.

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

    exports_init = app_dir / "exports" / "__init__.py"
    if exports_init.exists() and "ExcelExporter" in exports_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "ExcelExporter already present in app/exports/__init__.py — Excel export already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/exports/ (excel.py, formatters.py, __init__.py),",
                "         app/api/routes/excel_export.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    pkg_dir = app_dir / "exports"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "exports_init.py.tmpl", dest=exports_init, substitutions={})
    files_created.append(str(exports_init))

    excel_file = pkg_dir / "excel.py"
    render_to(_HERE, "excel.py.tmpl", dest=excel_file, substitutions={})
    files_created.append(str(excel_file))

    formatters_file = pkg_dir / "formatters.py"
    render_to(_HERE, "formatters.py.tmpl", dest=formatters_file, substitutions={})
    files_created.append(str(formatters_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "excel_export.py"
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
            "Excel export layer added: ExcelExporter (openpyxl lazy import), "
            "cell formatting, auto-width columns, StreamingResponse for large files.",
            "Routes: POST /api/v1/exports/excel, GET /api/v1/exports/{id}/download.",
            "Config fields EXCEL_MAX_ROWS, EXCEL_CHUNK_SIZE added.",
        ],
        next_steps=[
            "pip install openpyxl  # install the Excel library",
            "Set EXCEL_MAX_ROWS and EXCEL_CHUNK_SIZE in .env if defaults need tuning.",
            "Restart the FastAPI app so the /exports/* routes are loaded.",
        ],
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_excel_export_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_excel_export_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    src = config_file.read_text()
    if "EXCEL_MAX_ROWS" in src:
        return
    block = (
        "\n"
        "    # --- Excel export — added by add_excel_export tool ---\n"
        "    EXCEL_MAX_ROWS: int = 100000\n"
        "    EXCEL_CHUNK_SIZE: int = 1000\n"
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
        import_line="from app.api.routes.excel_export import router as excel_export_router",
        include_line="api_router.include_router(excel_export_router)",
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
    if "openpyxl" in src.lower():
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "openpyxl>=3.1.0\n")


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
