"""TOOL-024: add_email_templates — add a production-grade transactional email layer.

Writes a Jinja2-powered email rendering pipeline, provider adapters
(Resend/Postmark/SMTP lazy-imported), 4 built-in template triples
(HTML + plaintext + subject), EmailDelivery audit model, async CRUD,
HTTP routes, an Alembic migration, and all required settings fields.

The tool is idempotent: a second run detects ``TemplateName`` in
``app/email/__init__.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_email_templates",
    "description": "Add a production-grade transactional email layer with Jinja2 templates, pluggable providers (Resend/Postmark/SMTP), and delivery audit.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_email_templates",
}

# Tenant column blocks for the ORM model
_TENANT_COL_TENANTED = (
    "    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n"
    "        Uuid,\n"
    '        ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    "        nullable=True,\n"
    "        index=True,\n"
    '        comment="Tenant owning this delivery record",\n'
    "    )"
)
_TENANT_COL_PLAIN = (
    "    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n"
    "        Uuid,\n"
    "        nullable=True,\n"
    "        index=True,\n"
    '        comment="Tenant owning this delivery record",\n'
    "    )"
)

# Tenant column blocks for the Alembic migration
_MIGRATION_TENANT_TENANTED = (
    "        sa.Column(\n"
    '            "tenant_id", sa.Uuid(),\n'
    '            sa.ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    "            nullable=True,\n"
    "        ),"
)
_MIGRATION_TENANT_PLAIN = '        sa.Column("tenant_id", sa.Uuid(), nullable=True),'

# Verbatim Jinja2 templates (4 x 3 files = 12 files)
_JINJA2_TEMPLATES = [
    "welcome.subject.txt",
    "welcome.html",
    "welcome.txt",
    "password_reset.subject.txt",
    "password_reset.html",
    "password_reset.txt",
    "email_verification.subject.txt",
    "email_verification.html",
    "email_verification.txt",
    "receipt.subject.txt",
    "receipt.html",
    "receipt.txt",
]


def add_email_templates(
    inp: ToolInput,
    *,
    provider: str = "resend",
    from_address: str = "noreply@example.com",
    from_name: str = "Your App",
    reply_to: str | None = None,
    default_locale: str = "en",
) -> ToolResult:
    """Add a production-grade transactional email layer to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.
        provider: Default email provider (resend/postmark/smtp).
        from_address: Default From: address.
        from_name: Default From: display name.
        reply_to: Optional Reply-To address.
        default_locale: Default locale for template lookup.

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

    email_pkg_init = app_dir / "email" / "__init__.py"
    if email_pkg_init.exists() and "TemplateName" in email_pkg_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "TemplateName already present in app/email/__init__.py — email templates already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    has_tenants = (app_dir / "models" / "tenant.py").exists()
    reply_to_value = reply_to or ""

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/email/ (registry, render, providers, service),",
                "         12 template files (4 templates x 3 files each),",
                "         app/models/email_delivery.py, app/schemas/email.py,",
                "         app/crud/email_delivery.py, app/api/routes/email.py,",
                "         and an Alembic migration for the email_deliveries table"
                + (" (tenant-aware)" if has_tenants else "")
                + ".",
                f"         provider={provider}, from={from_address!r}, default_locale={default_locale}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — email package skeleton
    pkg_dir = app_dir / "email"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "email_pkg_init.py.tmpl", dest=email_pkg_init, substitutions={})
    files_created.append(str(email_pkg_init))

    for tmpl_name, dest_name in [
        ("registry.py.tmpl", "registry.py"),
        ("render.py.tmpl", "render.py"),
        ("service.py.tmpl", "service.py"),
    ]:
        dest = pkg_dir / dest_name
        render_to(_HERE, tmpl_name, dest=dest, substitutions={})
        files_created.append(str(dest))

    # Step 2 — provider adapters
    providers_dir = pkg_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

    for tmpl_name, dest_name in [
        ("providers_init.py.tmpl", "__init__.py"),
        ("provider_base.py.tmpl", "base.py"),
        ("provider_resend.py.tmpl", "resend.py"),
        ("provider_postmark.py.tmpl", "postmark.py"),
        ("provider_smtp.py.tmpl", "smtp.py"),
    ]:
        dest = providers_dir / dest_name
        render_to(_HERE, tmpl_name, dest=dest, substitutions={})
        files_created.append(str(dest))

    # Step 3 — Jinja2 template files (verbatim, preserves {{ }} syntax)
    tpl_dir = pkg_dir / "templates" / "en"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    for name in _JINJA2_TEMPLATES:
        dest = tpl_dir / name
        _write_verbatim(f"{name}.tmpl", dest)
        files_created.append(str(dest))

    # Step 4 — EmailDelivery model (tenant-aware variant)
    model_file = app_dir / "models" / "email_delivery.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    tenant_col = _TENANT_COL_TENANTED if has_tenants else _TENANT_COL_PLAIN
    _write_and_replace(
        "model_email_delivery.py.tmpl", model_file, {"TENANT_PLACEHOLDER": tenant_col}
    )
    files_created.append(str(model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("email_delivery", "EmailDelivery")])
        files_modified.append(str(models_init))

    # Step 5 — schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "email.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    # Step 6 — CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "email_delivery.py"
    render_to(_HERE, "crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    # Step 7 — routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "email.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    # Step 8 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        migration_tenant = _MIGRATION_TENANT_TENANTED if has_tenants else _MIGRATION_TENANT_PLAIN
        migration_file = versions_dir / "add_email_templates.py"
        _write_and_replace(
            "migration.py.tmpl",
            migration_file,
            {"DOWN_REV": down_rev, "TENANT_PLACEHOLDER": migration_tenant},
        )
        files_created.append(str(migration_file))

    # Step 9 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            provider=provider,
            from_address=from_address,
            from_name=from_name,
            reply_to=reply_to_value,
            default_locale=default_locale,
        )
        files_modified.append(str(config_file))

    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    env_example = project / ".env.example"
    if env_example.exists():
        _patch_env_example(env_example)
        files_modified.append(str(env_example))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Email templates added: Jinja2 renderer, provider adapters "
            "(resend/postmark/smtp, lazy-imported), 4 built-in templates "
            "(welcome, password_reset, email_verification, receipt) with "
            "HTML + plaintext + subject triples.",
            "EmailDelivery audit model"
            + (" (tenant-aware)" if has_tenants else "")
            + " persists every send attempt with a REDACTED recipient.",
            "GET /email/preview/{template_name} is available only outside production.",
            "GET /email/deliveries/me lists the current user's email deliveries.",
            f"Default provider: {provider}.  Switch at runtime via EMAIL_PROVIDER env.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # ensures jinja2 is installed",
            "Install your chosen provider SDK only when needed: `pip install resend` or `pip install postmark`.",
            "alembic upgrade head",
            "Set EMAIL_FROM + provider API key in .env.",
            "Restart the FastAPI app so the /email/* routes are loaded.",
        ],
        execution_time_ms=_ms(start),
    )


def _write_verbatim(tmpl_name: str, dest: Path) -> None:
    """Write a template file verbatim (no substitution — preserves Jinja2 syntax).

    Args:
        tmpl_name: Template filename under templates/.
        dest: Destination path to write.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = (_HERE / "templates" / tmpl_name).read_text()
    dest.write_text(content)


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
    emitted = project / "tests" / "test_add_email_templates_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_email_templates_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(
    config_file: Path,
    *,
    provider: str,
    from_address: str,
    from_name: str,
    reply_to: str,
    default_locale: str,
) -> None:
    src = config_file.read_text()
    if "EMAIL_PROVIDER" in src:
        return
    block = (
        "\n"
        "    # --- Email templates — added by add_email_templates tool ---\n"
        f'    EMAIL_PROVIDER: str = "{provider}"\n'
        f'    EMAIL_FROM: str = "{from_address}"\n'
        f'    EMAIL_FROM_NAME: str = "{from_name}"\n'
        f'    EMAIL_REPLY_TO: str = "{reply_to}"\n'
        f'    EMAIL_DEFAULT_LOCALE: str = "{default_locale}"\n'
        '    RESEND_API_KEY: str = ""\n'
        '    POSTMARK_API_KEY: str = ""\n'
        '    SMTP_HOST: str = ""\n'
        "    SMTP_PORT: int = 587\n"
        '    SMTP_USERNAME: str = ""\n'
        '    SMTP_PASSWORD: str = ""\n'
        "    SMTP_USE_TLS: bool = True\n"
        "    EMAIL_PREVIEW_ENABLED_IN_PROD: bool = False\n"
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
        import_line="from app.api.routes.email import router as email_router",
        include_line="api_router.include_router(email_router)",
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


def _patch_env_example(env_example: Path) -> None:
    src = env_example.read_text()
    if "EMAIL_PROVIDER" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    block = (
        "\n"
        "# --- Email templates (add_email_templates) ---\n"
        "EMAIL_PROVIDER=resend\n"
        "EMAIL_FROM=noreply@example.com\n"
        "EMAIL_FROM_NAME=Your App\n"
        "RESEND_API_KEY=\n"
        "POSTMARK_API_KEY=\n"
        "SMTP_HOST=\n"
        "SMTP_PORT=587\n"
        "SMTP_USERNAME=\n"
        "SMTP_PASSWORD=\n"
    )
    env_example.write_text(src + trailing + block)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
