"""TOOL-082: add_push_notifications_native — APNs + FCM real push notifications.

Honesty (§11 N2, F-06): provider SDKs (``firebase_admin``, ``apns2``) are lazy-
imported; missing-SDK → ``False`` + WARNING log (no retry, no token-refresh).
Stale FCM token responses (``Unregistered`` / ``BadDeviceToken``) and APNs
``BadDeviceToken`` are NOT detected here — silent drop. The emitted test
asserts that advisory behaviour, not delivery.
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
    "name": "fastapi_resiliency_add_push_notifications_native",
    "description": (
        "Add production APNs + FCM push notifications with PushService, "
        "DeviceToken model, CRUD helpers, and REST routes. All SDKs lazy-imported."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_push_notifications_native",
}


def add_push_notifications_native(inp: ToolInput) -> ToolResult:
    """Add APNs + FCM push notifications to a FastAPI project."""
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

    push_init = app_dir / "push" / "__init__.py"
    if push_init.exists() and "PushService" in push_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "PushService already present in app/push/__init__.py — "
                "push notifications already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/push/ (service, providers/fcm.py, providers/apns.py),",
                "         app/models/device_token.py, app/schemas/push.py,",
                "         app/crud/device_token.py, app/api/routes/push.py,",
                "         and an Alembic migration for the `device_tokens` table.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    _write_push_package(app_dir, files_created)

    model_file = app_dir / "models" / "device_token.py"
    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init)
        files_modified.append(str(models_init))

    schema_file = app_dir / "schemas" / "push.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    crud_file = app_dir / "crud" / "device_token.py"
    render_to(_HERE, "crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    routes_file = app_dir / "api" / "routes" / "push.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "add_device_tokens.py"
        render_to(_HERE, "migration.py.tmpl", dest=mig_file, substitutions={"down_rev": down_rev})
        files_created.append(str(mig_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
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
            "Push notification layer added: FCM (firebase_admin) + APNs (apns2), "
            "both lazy-imported.",
            "PushService.send_to_device routes to FCM or APNs based on platform field.",
            "PushService.send_to_topic broadcasts to an FCM topic.",
            "POST /push/register-device — register a device token.",
            "POST /push/send             — send a push notification.",
            "DELETE /push/devices/{id}  — unregister a device token.",
            "WARNING: provider SDKs are best-effort — missing firebase_admin/apns2 → False + log.",
            "WARNING: stale tokens (FCM Unregistered, APNs BadDeviceToken) are NOT auto-pruned — "
            "drop+log only. Refresh policy is owner's responsibility.",
        ],
        next_steps=[
            "alembic upgrade head",
            "pip install firebase-admin  # for FCM/Android",
            "pip install apns2           # for APNs/iOS",
            "Set FCM_CREDENTIALS_PATH (JSON service account file) in .env.",
            "Set APNS_KEY_PATH, APNS_KEY_ID, APNS_TEAM_ID in .env for iOS.",
            "Set APNS_BUNDLE_ID to your app's bundle identifier.",
            "Restart the FastAPI app so /push/* routes are loaded.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _write_push_package(app_dir: Path, files_created: list[str]) -> None:
    """Create the ``app/push/`` package with __init__, service, and providers."""
    push_dir = app_dir / "push"
    files = (
        ("__init__.py", "push_init.py.tmpl"),
        ("service.py", "service.py.tmpl"),
        ("providers/__init__.py", "providers_init.py.tmpl"),
        ("providers/fcm.py", "fcm_provider.py.tmpl"),
        ("providers/apns.py", "apns_provider.py.tmpl"),
    )
    for rel, tmpl in files:
        dest = push_dir / rel
        render_to(_HERE, tmpl, dest=dest, substitutions={})
        files_created.append(str(dest))


def _patch_models_init(models_init: Path) -> None:
    """Register DeviceToken in ``app/models/__init__.py``."""
    content = models_init.read_text()
    marker = "from app.models.device_token import DeviceToken"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject push notification settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "FCM_CREDENTIALS_PATH" in src:
        return

    block = (
        "\n"
        "    # --- Push notifications — added by add_push_notifications_native tool ---\n"
        '    FCM_CREDENTIALS_PATH: str = ""\n'
        '    APNS_KEY_PATH: str = ""\n'
        '    APNS_KEY_ID: str = ""\n'
        '    APNS_TEAM_ID: str = ""\n'
        '    APNS_BUNDLE_ID: str = ""\n'
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
    """Register the push router in ``app/routes/__init__.py``."""
    src = routes_init.read_text()
    import_line = "from app.api.routes.push import router as push_router"
    include_line = "api_router.include_router(push_router)"
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
    """Emit ``tests/test_add_push_notifications_native_emitted.py`` into the project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_push_notifications_native_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_push_notifications_native_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
