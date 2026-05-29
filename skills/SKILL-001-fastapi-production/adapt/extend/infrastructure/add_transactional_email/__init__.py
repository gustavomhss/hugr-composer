"""TOOL-081: add_transactional_email — Resend/Postmark/SendGrid adapter with delivery tracking.

Writes lazy provider adapters, a DeliveryTracker, EmailEvent model,
schemas, webhook routes, and an Alembic migration.

The tool is idempotent: a second run detects ``DeliveryTracker`` in
``app/email/delivery_tracker.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_transactional_email",
    "description": (
        "Add Resend/Postmark/SendGrid email adapters with delivery tracking "
        "(sent/delivered/bounced/complained events), PII-safe audit model, "
        "and provider webhook routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_transactional_email",
}


def add_transactional_email(inp: ToolInput) -> ToolResult:
    """Add a transactional email layer (multi-provider + delivery tracking) to a FastAPI project.

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
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    tracker_file = app_dir / "email" / "delivery_tracker.py"
    if tracker_file.exists() and "DeliveryTracker" in tracker_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "DeliveryTracker already present in app/email/delivery_tracker.py — transactional email layer already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/email/providers/ (resend, postmark, sendgrid — lazy),",
                "         app/email/delivery_tracker.py, app/models/email_event.py,",
                "         app/schemas/email_event.py, app/api/routes/email_events.py,",
                "         and an Alembic migration for the email_events table.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — email/providers package
    providers_dir = app_dir / "email" / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

    for tmpl_name, dest_name in [
        ("providers_init.py.tmpl", "__init__.py"),
        ("resend_provider.py.tmpl", "resend_provider.py"),
        ("postmark_provider.py.tmpl", "postmark_provider.py"),
        ("sendgrid_provider.py.tmpl", "sendgrid_provider.py"),
    ]:
        dest = providers_dir / dest_name
        render_to(_HERE, tmpl_name, dest=dest, substitutions={})
        files_created.append(str(dest))

    # Step 2 — delivery tracker
    email_dir = app_dir / "email"
    email_dir.mkdir(parents=True, exist_ok=True)
    dt_dest = email_dir / "delivery_tracker.py"
    render_to(_HERE, "delivery_tracker.py.tmpl", dest=dt_dest, substitutions={})
    files_created.append(str(dt_dest))

    # Step 3 — EmailEvent ORM model
    model_file = app_dir / "models" / "email_event.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "model_email_event.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init)
        files_modified.append(str(models_init))

    # Step 4 — schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "email_event.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    # Step 5 — routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "email_events.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    # Step 6 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        migration_file = versions_dir / "add_email_events.py"
        _write_and_replace(
            "migration.py.tmpl",
            migration_file,
            {"DOWN_REV_PLACEHOLDER": down_rev},
        )
        files_created.append(str(migration_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8 — register router
    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Transactional email layer added: Resend, Postmark, SendGrid adapters "
            "(all lazy-imported -- only install what you use).",
            "DeliveryTracker records sent/delivered/bounced/complained events in email_events table.",
            "Recipient stored as recipient_redacted (u***@example.com) -- PII never in DB.",
            "POST /email/webhook/{provider} -- ingest delivery events from Resend/Postmark/SendGrid.",
            "GET /email/events -- list recent email events (admin).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set EMAIL_PROVIDER in .env (resend | postmark | sendgrid).",
            "Install your chosen provider SDK: pip install resend  OR  pip install postmarker  OR  pip install sendgrid.",
            "Set the corresponding API key: RESEND_API_KEY / POSTMARK_API_KEY / SENDGRID_API_KEY.",
            "Configure webhook URLs in your email provider dashboard to POST to /email/webhook/{provider}.",
        ],
        execution_time_ms=_ms(start),
    )


def _write_and_replace(tmpl_name: str, dest: Path, replacements: dict[str, str]) -> None:
    """Read a template verbatim and apply plain-string replacements.

    Args:
        tmpl_name: Template filename under templates/.
        dest: Destination path to write.
        replacements: Dict of marker -> replacement string.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = (_HERE / "templates" / tmpl_name).read_text()
    for marker, value in replacements.items():
        content = content.replace(marker, value)
    dest.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_transactional_email_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_transactional_email_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_models_init(models_init: Path) -> None:
    content = models_init.read_text()
    marker = "from app.models.email_event import EmailEvent"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    src = config_file.read_text()
    if "EMAIL_PROVIDER" in src:
        return
    block = (
        "\n"
        "    # --- Transactional email — added by add_transactional_email tool ---\n"
        '    EMAIL_PROVIDER: str = "resend"\n'
        '    RESEND_API_KEY: str = ""\n'
        '    POSTMARK_API_KEY: str = ""\n'
        '    SENDGRID_API_KEY: str = ""\n'
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
    src = routes_init.read_text()
    import_line = "from app.api.routes.email_events import router as email_events_router"
    include_line = "api_router.include_router(email_events_router)"
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


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
