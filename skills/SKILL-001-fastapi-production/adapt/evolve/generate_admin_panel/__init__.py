"""TOOL-048: generate_admin_panel — auto-generate sqladmin admin panel.

Scaffolds ``app/admin/`` with one ``ModelView`` per discovered model,
an auth gate, audit logging via SQLAlchemy event listeners, CSV export
cap (10,000 rows), and read-only mode for sensitive models.

The tool is idempotent: if ``app/admin/__init__.py`` already exists and
contains the ``sqladmin`` fingerprint, returns ``status="no_op"``.

Warnings:
    - The emitted ``AdminAuth`` is a STUB with hard-coded ``admin/admin``
      credentials. It does NOT enforce RBAC and is NOT production-safe.
      Operators MUST swap the stub for real credential validation +
      role-based access policy before any production exposure.
    - The scaffold does NOT auto-register the admin mount in main.py:
      the patched main.py appends a commented-out create_admin snippet.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_resiliency_generate_admin_panel",
    "description": "Generate an admin panel (SQLAdmin or Starlette-admin) wired to all models.",
    "tags": ["evolve"],
    "entry": "generate_admin_panel",
}


def generate_admin_panel(
    inp: ToolInput,
    models: list[str] | None = None,
    mount_path: str = "/admin",
    auth_dependency: str = "require_admin",
    theme: str = "default",
    read_only_models: list[str] | None = None,
) -> ToolResult:
    """Scaffold a sqladmin admin panel for the given models."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"
    admin_dir = app_dir / "admin"
    read_only_models = read_only_models or []

    admin_init = admin_dir / "__init__.py"
    if admin_init.exists() and "sqladmin" in admin_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["sqladmin admin panel already present in app/admin/ — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if models is None:
        models = _discover_models(app_dir)

    if not models:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found. Generate models first or pass models= explicitly.",
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would scaffold admin panel for: {', '.join(models)}",
                f"[dry_run] mount_path={mount_path} read_only={read_only_models}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    admin_dir.mkdir(parents=True, exist_ok=True)
    views_dir = admin_dir / "views"
    views_dir.mkdir(exist_ok=True)

    view_imports = "\n".join(
        f"from app.admin.views.{m.lower()}_view import {m}Admin" for m in models
    )
    view_registrations = "\n    ".join(f"admin.add_view({m}Admin)" for m in models)
    render_to(
        _HERE,
        "admin_init.py.tmpl",
        dest=admin_init,
        substitutions={
            "mount_path": mount_path,
            "view_imports": view_imports,
            "view_registrations": view_registrations,
        },
    )
    files_created.append(str(admin_init))

    auth_file = admin_dir / "auth.py"
    render_to(_HERE, "auth.py.tmpl", dest=auth_file, substitutions={})
    files_created.append(str(auth_file))

    audit_file = admin_dir / "audit.py"
    render_to(_HERE, "audit.py.tmpl", dest=audit_file, substitutions={})
    files_created.append(str(audit_file))

    views_init = views_dir / "__init__.py"
    views_init.write_text('"""Admin model views package."""\n')
    files_created.append(str(views_init))

    for model_name in models:
        view_file = views_dir / f"{model_name.lower()}_view.py"
        is_ro = model_name in read_only_models
        bool_val = "False" if is_ro else "True"
        render_to(
            _HERE,
            "model_view.py.tmpl",
            dest=view_file,
            substitutions={
                "model_name": model_name,
                "lower": model_name.lower(),
                "can_create": bool_val,
                "can_edit": bool_val,
                "can_delete": bool_val,
            },
        )
        files_created.append(str(view_file))

    audit_model_file = app_dir / "models" / "audit_log.py"
    if not audit_model_file.exists():
        render_to(_HERE, "audit_log_model.py.tmpl", dest=audit_model_file, substitutions={})
        files_created.append(str(audit_model_file))

    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file, mount_path):
        files_modified.append(str(main_file))

    test_dir = project / "tests"
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "test_admin_panel.py"
    render_to(
        _HERE,
        "test_admin_panel.py.tmpl",
        dest=test_file,
        substitutions={
            "mount_path": mount_path,
            "models": repr(models),
            "read_only_models": repr(read_only_models),
        },
    )
    files_created.append(str(test_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Admin panel scaffolded at {mount_path}",
            f"Models: {', '.join(models)}",
            f"Read-only models: {read_only_models or 'none'}",
            "CSV export hard-capped at 10,000 rows.",
            "Audit logging via SQLAlchemy event listeners.",
        ],
        next_steps=[
            "pip install sqladmin",
            "alembic revision --autogenerate -m 'add audit_log table'",
            "alembic upgrade head",
            f"Visit {mount_path} — auth gate: {auth_dependency}",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _discover_models(app_dir: Path) -> list[str]:
    """Discover SQLAlchemy model names from app/models/."""
    models_dir = app_dir / "models"
    skip = {"base", "mixins", "__init__", "audit_log", "outbox_event"}
    names = []
    for f in sorted(models_dir.glob("*.py")):
        if f.stem.lower() not in skip:
            names.append("".join(w.capitalize() for w in f.stem.split("_")))
    return names


def _patch_main(main_file: Path, mount_path: str) -> bool:
    """Append a commented-out admin mount snippet to app/main.py."""
    src = main_file.read_text()
    if "create_admin" in src or "sqladmin" in src:
        return False
    snippet = (
        "\n# Admin panel — added by generate_admin_panel tool\n"
        "# from app.admin import create_admin\n"
        "# from app.core.db import engine\n"
        "# admin = create_admin(app, engine)\n"
        f"# (sqladmin auto-mounts at {mount_path})\n"
    )
    main_file.write_text(src + snippet)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_generate_admin_panel_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_generate_admin_panel_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_generate_admin_panel_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
