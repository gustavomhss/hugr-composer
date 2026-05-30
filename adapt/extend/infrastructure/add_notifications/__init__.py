"""TOOL-063: add_notifications — in-app notification layer with channel dispatch.

Honesty (§11 N1-N2, F-06): fan-out is best-effort (no retry budget, no exactly-once);
``firebase_admin`` is lazy and missing-SDK is silent stub log; channel iteration
order (in_app→push→email) is fixed by the if/elif ladder in the emitted template.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_notifications",
    "description": (
        "Add a production-grade in-app notification layer with channel dispatch "
        "(in_app, push FCM stub, email bridge), unread badge, and bulk mark-read."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_notifications",
}


def add_notifications(inp: ToolInput, *, max_per_page: int = 50) -> ToolResult:
    """Add a production-grade notification layer to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    notif_init = app_dir / "notifications" / "__init__.py"
    if notif_init.exists() and "NotificationService" in notif_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "NotificationService already present in app/notifications/__init__.py — "
                "notifications already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    has_email = (app_dir / "email" / "__init__.py").exists()

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/notifications/ (service, channels),",
                "         app/models/notification.py, app/schemas/notification.py,",
                "         app/crud/notification.py, app/api/routes/notifications.py,",
                "         and an Alembic migration for the `notifications` table.",
                f"         email_bridge={'enabled (add_email_templates detected)' if has_email else 'stub (no app/email/ found)'}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    _write_notifications_package(app_dir, files_created, has_email=has_email)

    model_file = app_dir / "models" / "notification.py"
    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("notification", "Notification")])
        files_modified.append(str(models_init))

    schema_file = app_dir / "schemas" / "notification.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    crud_file = app_dir / "crud" / "notification.py"
    render_to(_HERE, "crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    routes_file = app_dir / "api" / "routes" / "notifications.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "add_notifications.py"
        render_to(_HERE, "migration.py.tmpl", dest=mig_file, substitutions={"down_rev": down_rev})
        files_created.append(str(mig_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, max_per_page=max_per_page)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Notification layer added: in_app channel (DB insert), push channel "
            "(FCM stub — firebase_admin lazy-imported), "
            + (
                "email channel (bridged to app/email/)."
                if has_email
                else "email channel stub (add_email_templates not detected)."
            ),
            "GET /notifications — paginated list (newest first).",
            "POST /notifications/{id}/read — mark single notification read.",
            "POST /notifications/read-all — bulk mark-all-read (single UPDATE).",
            "GET /notifications/unread-count — fast COUNT(*) badge query.",
            "WARNING: fan-out is best-effort — no per-channel retry budget, no exactly-once "
            "guarantee. Unknown channels and missing firebase_admin log a warning and drop.",
            "WARNING: emitted test asserts advisory signal (no crash + log) only — "
            "not delivery; this matches the actual emitted dispatch semantics.",
        ],
        next_steps=[
            "alembic upgrade head",
            "To enable push notifications: pip install firebase-admin, "
            "then set FIREBASE_CREDENTIALS_PATH in .env.",
            "Inject NotificationService where needed: "
            "from app.notifications import NotificationService",
            "Restart the FastAPI app so /notifications routes are loaded.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _write_notifications_package(
    app_dir: Path,
    files_created: list[str],
    *,
    has_email: bool,
) -> None:
    """Create ``app/notifications/`` with __init__, service, channels."""
    pkg_dir = app_dir / "notifications"
    init_file = pkg_dir / "__init__.py"
    render_to(_HERE, "notifications_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    service_file = pkg_dir / "service.py"
    render_to(_HERE, "service.py.tmpl", dest=service_file, substitutions={})
    files_created.append(str(service_file))

    channels_template = "channels_with_email.py.tmpl" if has_email else "channels_stub.py.tmpl"
    channels_file = pkg_dir / "channels.py"
    render_to(_HERE, channels_template, dest=channels_file, substitutions={})
    files_created.append(str(channels_file))


def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker not in content:
            new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path, *, max_per_page: int) -> None:
    """Inject notification settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "NOTIFICATION_CHANNELS" in src:
        return

    block = (
        "\n"
        "    # --- Notifications — added by add_notifications tool ---\n"
        '    NOTIFICATION_CHANNELS: list[str] = ["in_app"]\n'
        f"    NOTIFICATION_MAX_PER_PAGE: int = {max_per_page}\n"
        '    FIREBASE_CREDENTIALS_PATH: str = ""\n'
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
    """Register the notifications router in ``app/routes/__init__.py``."""
    _register_router(
        routes_init,
        import_line="from app.api.routes.notifications import router as notifications_router",
        include_line="api_router.include_router(notifications_router)",
    )


def _register_router(routes_init: Path, *, import_line: str, include_line: str) -> None:
    """Idempotently add an import + ``api_router.include_router`` call."""
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import = idx
    if last_app_import == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import = idx - 1
                break
    lines.insert(last_app_import + 1, import_line)
    last_include = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include = idx
    if last_include == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include = idx
                break
    lines.insert(last_include + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit ``tests/test_add_notifications_emitted.py`` into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_notifications_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_notifications_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
