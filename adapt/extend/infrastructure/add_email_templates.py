"""TOOL-024: add_email_templates — add a production-grade transactional email layer.

Writes a Jinja2-powered email rendering pipeline, a pluggable provider
adapter (Resend / Postmark / SMTP), 4 built-in templates (welcome,
password_reset, email_verification, receipt) shipped as HTML + plaintext
+ subject triples, an ``EmailDelivery`` audit model (tenant-aware when
``app/models/tenant.py`` exists), async CRUD helpers, HTTP routes for
dev-mode preview + per-user delivery listing, an Alembic migration, and
every required settings field.

Why a template + provider abstraction (and not a direct SMTP call)?

* **Locale fallback** — templates live under
  ``app/email/templates/{locale}/`` and the renderer falls back cleanly
  from ``{locale}`` → ``"en"`` → first available, so a request from a
  Portuguese-speaking user automatically degrades to English rather
  than 500-ing.
* **HTML + plaintext pairs** — every message ships a plaintext fallback
  alongside the HTML body so it still renders in mutt, Apple Mail
  preview panes, and spam-filter scanners.  Missing the plaintext part
  is one of the biggest hidden deliverability killers.
* **Provider adapter** — swapping Resend → Postmark → SMTP is a
  one-line config change (``EMAIL_PROVIDER=postmark``); adapters
  import their SDKs LAZILY so the app boots cleanly even when neither
  third-party package is installed.
* **Audit trail** — every send attempt creates an ``email_deliveries``
  row with a REDACTED recipient (``u***@example.com``) so operators
  can troubleshoot bounces without leaking PII into logs.
* **Dev preview endpoint** — ``GET /email/preview/{template_name}`` is
  exposed only when ``settings.ENVIRONMENT != "production"`` (or the
  ``EMAIL_PREVIEW_ENABLED_IN_PROD`` escape hatch is explicitly set);
  it lets designers iterate on templates without sending real mail.

Security / correctness guarantees:

* Third-party SDKs (``resend``, ``postmark``) are imported LAZILY inside
  each provider's ``send()`` method so the application can boot without
  them.  The tool does NOT add them to ``requirements.txt`` — operators
  install only what they use.
* Recipient addresses are NEVER written to logs in full form.  The
  helper ``_redact_email`` returns ``u***@example.com`` and the
  ``EmailDelivery.to_email_redacted`` column only stores the redacted
  form, so a DB dump cannot leak addresses.
* Provider API keys (``RESEND_API_KEY``, ``POSTMARK_API_KEY``) are read
  on every call from ``settings`` and are NEVER logged or echoed back
  to a caller.
* Jinja2's ``autoescape=True`` is enabled for all HTML templates to
  prevent XSS via untrusted context data.
* The preview endpoint returns HTTP 403 when ``ENVIRONMENT ==
  "production"`` and ``EMAIL_PREVIEW_ENABLED_IN_PROD`` is ``False``.
* Every generated function is kept ≤50 LOC (enforced by the tool's
  self-verification script).

The tool is idempotent: a second run detects the ``TemplateName`` fingerprint
in ``app/email/__init__.py`` and returns ``status="no_op"`` without
touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_email_templates import add_email_templates

    result = add_email_templates(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/email/registry.py", …]
    print(result.next_steps)    # ["Set RESEND_API_KEY in .env", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_email_templates",
    "description": "Add a production-grade transactional email layer with Jinja2 templates, pluggable providers (Resend/Postmark/SMTP), and delivery audit.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_email_templates",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

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

    Creates the ``app/email/`` package (registry, renderer, provider
    adapters, service), 4 Jinja2 template triples (HTML + plaintext +
    subject), the ``EmailDelivery`` audit model + schema + CRUD, HTTP
    routes (preview + per-user delivery list), an Alembic migration, and
    every required email settings field.  Patches ``app/core/config.py``,
    ``app/models/__init__.py``, ``app/routes/__init__.py`` and
    ``requirements.txt``.  Does NOT patch ``app/main.py`` — the email
    layer is stateless and requires no lifespan hook.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.
        provider: Default email provider.  One of ``"resend"``,
            ``"postmark"``, ``"smtp"``.  Maps to
            ``settings.EMAIL_PROVIDER`` — operators can override at
            runtime via env var.  Defaults to ``"resend"``.
        from_address: Default ``From:`` address for every message.
            Maps to ``settings.EMAIL_FROM``.
        from_name: Default ``From:`` display name.  Maps to
            ``settings.EMAIL_FROM_NAME``.
        reply_to: Optional ``Reply-To:`` address.  When ``None`` the
            setting is stored as an empty string (pydantic-settings
            cannot default to ``None`` in a ``str`` field).
        default_locale: Default locale for template lookup.  Maps to
            ``settings.EMAIL_DEFAULT_LOCALE``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``,
        ``files_modified``, ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    email_pkg_init = app_dir / "email" / "__init__.py"
    if email_pkg_init.exists() and "TemplateName" in email_pkg_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "TemplateName already present in app/email/__init__.py — "
                "email templates already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
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
                "         and an Alembic migration for the `email_deliveries` table"
                + (" (tenant-aware)" if has_tenants else "")
                + ".",
                f"         provider={provider}, from={from_address!r}, "
                f"default_locale={default_locale}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — email package skeleton + registry + renderer + service
    _write_email_package(app_dir, files_created)

    # Step 2 — provider adapters (lazy imports)
    _write_email_providers(app_dir, files_created)

    # Step 3 — built-in templates (4 templates x 3 files = 12 files)
    _write_email_templates(app_dir, files_created)

    # Step 4 — EmailDelivery model
    model_file = app_dir / "models" / "email_delivery.py"
    _write_email_delivery_model(model_file, has_tenants=has_tenants)
    files_created.append(str(model_file))

    # Register EmailDelivery in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("email_delivery", "EmailDelivery")])
        files_modified.append(str(models_init))

    # Step 5 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "email.py"
    schema_file.write_text(_EMAIL_SCHEMAS_TEMPLATE)
    files_created.append(str(schema_file))

    # Step 6 — Async CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "email_delivery.py"
    crud_file.write_text(_EMAIL_CRUD_TEMPLATE)
    files_created.append(str(crud_file))

    # Step 7 — HTTP routes (preview + list mine)
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "email.py"
    routes_file.write_text(_EMAIL_ROUTES_TEMPLATE)
    files_created.append(str(routes_file))

    # Step 8 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_email_migration(
            versions_dir, has_tenants=has_tenants
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

    # Step 10 — register email router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 11 — ensure jinja2 in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Step 12 — patch .env.example (documentation only)
    env_example = project / ".env.example"
    if env_example.exists():
        _patch_env_example(env_example)
        files_modified.append(str(env_example))

    # Validate every generated Python file parses
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

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
            "GET /email/preview/{template_name} is available only outside "
            "production (gated on settings.ENVIRONMENT).",
            "GET /email/deliveries/me lists the current user's email deliveries.",
            f"Default provider: {provider}.  Switch at runtime via EMAIL_PROVIDER env.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # ensures jinja2 is installed",
            "Install your chosen provider SDK only when needed: "
            "`pip install resend` or `pip install postmark`.",
            "alembic upgrade head",
            "Set EMAIL_FROM + provider API key "
            "(RESEND_API_KEY / POSTMARK_API_KEY / SMTP_* envs) in .env.",
            "Restart the FastAPI app so the /email/* routes are loaded.",
            "In dev, preview: GET /api/v1/email/preview/welcome?locale=en",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body.
# ---------------------------------------------------------------------------

def _write_email_package(app_dir: Path, files_created: list[str]) -> None:
    """Create the ``app/email/`` package with registry, renderer, service.

    Writes ``__init__.py``, ``registry.py``, ``render.py``, ``service.py``
    and appends the created file paths to *files_created*.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
    """
    pkg_dir = app_dir / "email"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    init_file = pkg_dir / "__init__.py"
    init_file.write_text(_EMAIL_PKG_INIT_TEMPLATE)
    files_created.append(str(init_file))

    registry_file = pkg_dir / "registry.py"
    registry_file.write_text(_EMAIL_REGISTRY_TEMPLATE)
    files_created.append(str(registry_file))

    render_file = pkg_dir / "render.py"
    render_file.write_text(_EMAIL_RENDER_TEMPLATE)
    files_created.append(str(render_file))

    service_file = pkg_dir / "service.py"
    service_file.write_text(_EMAIL_SERVICE_TEMPLATE)
    files_created.append(str(service_file))


def _write_email_providers(app_dir: Path, files_created: list[str]) -> None:
    """Create the ``app/email/providers/`` package with 3 lazy adapters.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
    """
    providers_dir = app_dir / "email" / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "__init__.py": _EMAIL_PROVIDERS_INIT_TEMPLATE,
        "base.py": _EMAIL_PROVIDER_BASE_TEMPLATE,
        "resend.py": _EMAIL_PROVIDER_RESEND_TEMPLATE,
        "postmark.py": _EMAIL_PROVIDER_POSTMARK_TEMPLATE,
        "smtp.py": _EMAIL_PROVIDER_SMTP_TEMPLATE,
    }
    for name, content in files.items():
        p = providers_dir / name
        p.write_text(content)
        files_created.append(str(p))


def _write_email_templates(app_dir: Path, files_created: list[str]) -> None:
    """Write 4 built-in templates x 3 files each = 12 template files.

    Templates live under ``app/email/templates/en/``.  Each template
    ships a ``.subject.txt``, ``.html``, and ``.txt`` sibling so the
    renderer can produce a full ``(subject, html, text)`` triple.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
    """
    tpl_dir = app_dir / "email" / "templates" / "en"
    tpl_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        "welcome": _WELCOME_TEMPLATE_TRIPLE,
        "password_reset": _PASSWORD_RESET_TEMPLATE_TRIPLE,
        "email_verification": _EMAIL_VERIFICATION_TEMPLATE_TRIPLE,
        "receipt": _RECEIPT_TEMPLATE_TRIPLE,
    }
    for name, triple in templates.items():
        for ext, content in triple.items():
            p = tpl_dir / f"{name}.{ext}"
            p.write_text(content)
            files_created.append(str(p))


def _write_email_delivery_model(dest: Path, *, has_tenants: bool = False) -> None:
    """Write ``app/models/email_delivery.py`` with the audit model.

    Args:
        dest: Absolute path for the new file.
        has_tenants: Whether ``app/models/tenant.py`` exists.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tenant_col = (
        _EMAIL_DELIVERY_TENANT_COL_TENANTED
        if has_tenants
        else _EMAIL_DELIVERY_TENANT_COL_PLAIN
    )
    content = _EMAIL_DELIVERY_MODEL_TEMPLATE.replace(
        "TENANT_PLACEHOLDER", tenant_col
    )
    dest.write_text(content)


def _write_email_migration(versions_dir: Path, *, has_tenants: bool = False) -> Path:
    """Generate ``alembic/versions/add_email_templates.py``.

    Uses ``find_migration_head`` to chain cleanly onto the existing
    Alembic head.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.
        has_tenants: Whether multi-tenancy is installed.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    tenant_col = (
        _EMAIL_MIGRATION_TENANT_TENANTED
        if has_tenants
        else _EMAIL_MIGRATION_TENANT_PLAIN
    )
    content = (
        _EMAIL_MIGRATION_TEMPLATE
        .replace("DOWN_REV", down_rev)
        .replace("TENANT_PLACEHOLDER", tenant_col)
    )
    migration_file = versions_dir / "add_email_templates.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Config / init / requirements patches
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to ``app/models/__init__.py``.
        class_imports: List of ``(module, class)`` tuples to register.
    """
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
    """Inject email settings into the ``Settings`` class body.

    The fields must live INSIDE ``class Settings`` so pydantic-settings
    picks them up from env vars.  Anchored on the
    ``ACCESS_TOKEN_EXPIRE_MINUTES`` line — the canonical anchor used by
    every other ``extend/`` tool.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
        provider: Default ``EMAIL_PROVIDER`` value.
        from_address: Default ``EMAIL_FROM`` value.
        from_name: Default ``EMAIL_FROM_NAME`` value.
        reply_to: Default ``EMAIL_REPLY_TO`` value (empty string for None).
        default_locale: Default ``EMAIL_DEFAULT_LOCALE`` value.
    """
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
        '    SMTP_PORT: int = 587\n'
        '    SMTP_USERNAME: str = ""\n'
        '    SMTP_PASSWORD: str = ""\n'
        '    SMTP_USE_TLS: bool = True\n'
        '    EMAIL_PREVIEW_ENABLED_IN_PROD: bool = False\n'
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(
                settings_line,
                block.lstrip("\n") + "\n\n" + settings_line,
            )
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the email HTTP router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.email import router as email_router",
        include_line="api_router.include_router(email_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Copied verbatim from ``add_stripe_checkout`` to keep the tool suite
    consistent; callers should not re-implement router registration.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
    """
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
    """Ensure ``jinja2>=3.1.0`` is in ``requirements.txt``.

    Note: third-party provider packages (``resend``, ``postmark``) are
    NOT added — operators install only what they actually use, and the
    adapters import them lazily.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    if "jinja2" in src.lower():
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "jinja2>=3.1.0\n")


def _patch_env_example(env_example: Path) -> None:
    """Append email env var documentation to ``.env.example``.

    Args:
        env_example: Path to ``.env.example``.
    """
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


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the file to validate.

    Raises:
        SyntaxError: If the file has a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(
            f"Generated file {path} has a syntax error: {exc}"
        ) from exc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates — module-level constants, plain ``.replace()`` substitution.
# No f-string brace escaping.  Jinja2 ``{{ }}`` blocks only appear inside
# HTML/TXT template STRINGS that are written to disk verbatim — they are
# never interpolated as Python format strings.
# ---------------------------------------------------------------------------

_EMAIL_PKG_INIT_TEMPLATE = textwrap.dedent("""\
    \"\"\"Transactional email layer — Jinja2 templates + pluggable providers.

    Public API:
        TemplateName:   Enum of built-in template identifiers.
        render_email:   Render a template to (subject, html, text).
        send_email:     Synchronous send via the configured provider.
        enqueue_email:  Fire-and-forget send (arq if available, else
                        FastAPI BackgroundTasks).
    \"\"\"
    from __future__ import annotations

    from app.email.registry import TemplateName
    from app.email.render import render_email
    from app.email.service import enqueue_email, send_email

    __all__ = [
        "TemplateName",
        "render_email",
        "send_email",
        "enqueue_email",
    ]
""")


_EMAIL_REGISTRY_TEMPLATE = textwrap.dedent("""\
    \"\"\"Template registry — maps logical names to required context keys.

    The registry is the single source of truth for what context a
    template needs.  ``render_email`` validates the caller's context
    against this map and raises ``MissingContextError`` on mismatch so
    template bugs surface at the call site, not deep inside Jinja2.
    \"\"\"
    from __future__ import annotations

    from enum import Enum


    class TemplateName(str, Enum):
        \"\"\"Built-in transactional template identifiers.

        Values are the on-disk filename stems (without extension).
        The renderer expects three sibling files per template under
        ``app/email/templates/{locale}/``:

            * ``{name}.subject.txt`` — plaintext subject line
            * ``{name}.html``       — HTML body (inline CSS)
            * ``{name}.txt``        — plaintext body
        \"\"\"

        WELCOME = "welcome"
        PASSWORD_RESET = "password_reset"
        EMAIL_VERIFICATION = "email_verification"
        RECEIPT = "receipt"


    # Required context keys for each template.  Missing keys raise
    # MissingContextError before Jinja2 gets a chance to emit a
    # silent-empty-string.
    TEMPLATE_REQUIRED_CONTEXT: dict[TemplateName, tuple[str, ...]] = {
        TemplateName.WELCOME: ("user_name", "activation_url"),
        TemplateName.PASSWORD_RESET: ("user_name", "reset_url", "expires_in_hours"),
        TemplateName.EMAIL_VERIFICATION: ("user_name", "verification_url"),
        TemplateName.RECEIPT: (
            "user_name",
            "amount_formatted",
            "item_name",
            "receipt_url",
        ),
    }


    # Example context used by the dev preview endpoint so designers can
    # iterate on templates without constructing a payload by hand.
    TEMPLATE_EXAMPLE_CONTEXT: dict[TemplateName, dict[str, str]] = {
        TemplateName.WELCOME: {
            "app_name": "Your App",
            "user_name": "Alice",
            "activation_url": "https://example.com/activate?token=demo",
        },
        TemplateName.PASSWORD_RESET: {
            "app_name": "Your App",
            "user_name": "Alice",
            "reset_url": "https://example.com/reset?token=demo",
            "expires_in_hours": "2",
        },
        TemplateName.EMAIL_VERIFICATION: {
            "app_name": "Your App",
            "user_name": "Alice",
            "verification_url": "https://example.com/verify?token=demo",
        },
        TemplateName.RECEIPT: {
            "app_name": "Your App",
            "user_name": "Alice",
            "amount_formatted": "$49.00",
            "item_name": "Pro Plan (monthly)",
            "receipt_url": "https://example.com/receipts/demo",
        },
    }


    class MissingContextError(ValueError):
        \"\"\"Raised when a template is rendered with missing required keys.\"\"\"
""")


_EMAIL_RENDER_TEMPLATE = textwrap.dedent("""\
    \"\"\"Jinja2-powered email renderer with locale fallback.

    Responsibilities:
        * Load templates from ``app/email/templates/{locale}/``.
        * Fall back ``{locale} → "en" → first available`` so a Portuguese
          request never 500s just because a translation is missing.
        * Validate context keys against the registry and raise a
          ``MissingContextError`` pointing at the exact missing key.
        * Render ``(subject, html, text)`` as a dataclass.
    \"\"\"
    from __future__ import annotations

    from dataclasses import dataclass
    from pathlib import Path
    from typing import Any

    from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

    from app.email.registry import (
        TEMPLATE_REQUIRED_CONTEXT,
        MissingContextError,
        TemplateName,
    )


    TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"


    @dataclass(frozen=True)
    class RenderedEmail:
        \"\"\"A fully-rendered email message ready for a provider adapter.\"\"\"

        subject: str
        html: str
        text: str


    def _build_env(locale: str) -> Environment:
        \"\"\"Build a Jinja2 environment rooted at a specific locale directory.

        Args:
            locale: Locale subdirectory name (e.g. ``"en"``).

        Returns:
            A Jinja2 ``Environment`` with autoescape enabled for HTML.
        \"\"\"
        loader = FileSystemLoader(str(TEMPLATES_ROOT / locale))
        return Environment(
            loader=loader,
            autoescape=select_autoescape(["html"]),
            keep_trailing_newline=True,
        )


    def _resolve_locale(name: TemplateName, requested: str) -> str:
        \"\"\"Return a locale that has the given template, with fallback chain.

        Order: requested → ``"en"`` → first available directory that
        has ``{name}.html``.

        Args:
            name: Template identifier.
            requested: Caller-requested locale.

        Returns:
            A locale name that is guaranteed to contain ``{name}.html``.

        Raises:
            TemplateNotFound: If no locale has the template.
        \"\"\"
        for candidate in (requested, "en"):
            if (TEMPLATES_ROOT / candidate / f"{name.value}.html").exists():
                return candidate
        if TEMPLATES_ROOT.exists():
            for entry in sorted(TEMPLATES_ROOT.iterdir()):
                if entry.is_dir() and (entry / f"{name.value}.html").exists():
                    return entry.name
        raise TemplateNotFound(f"{name.value}.html")


    def _validate_context(name: TemplateName, context: dict[str, Any]) -> None:
        \"\"\"Ensure all required context keys are present.

        Args:
            name: Template identifier.
            context: Caller-supplied context dict.

        Raises:
            MissingContextError: If any required key is missing.
        \"\"\"
        required = TEMPLATE_REQUIRED_CONTEXT.get(name, ())
        missing = [k for k in required if k not in context]
        if missing:
            raise MissingContextError(
                f"template {name.value!r} missing required context keys: "
                + ", ".join(missing)
            )


    def render_email(
        name: TemplateName,
        context: dict[str, Any],
        locale: str = "en",
    ) -> RenderedEmail:
        \"\"\"Render a template triple into a ``RenderedEmail``.

        Args:
            name: Template identifier.
            context: Values to inject into the Jinja2 templates.
            locale: Preferred locale; falls back to ``"en"`` automatically.

        Returns:
            A ``RenderedEmail`` with non-empty ``subject``, ``html``, and ``text``.

        Raises:
            MissingContextError: If required context keys are missing.
            TemplateNotFound: If no locale has the template.
        \"\"\"
        _validate_context(name, context)
        resolved = _resolve_locale(name, locale)
        env = _build_env(resolved)
        subject = env.get_template(f"{name.value}.subject.txt").render(**context).strip()
        html = env.get_template(f"{name.value}.html").render(**context)
        text = env.get_template(f"{name.value}.txt").render(**context)
        return RenderedEmail(subject=subject, html=html, text=text)
""")


_EMAIL_SERVICE_TEMPLATE = textwrap.dedent("""\
    \"\"\"High-level email send helpers: ``send_email`` + ``enqueue_email``.

    * ``send_email`` renders the template, calls the configured provider
      adapter, and persists an ``EmailDelivery`` audit row — all within
      a single request/transaction.
    * ``enqueue_email`` dispatches the send off the critical path.  When
      the arq worker is wired (``app.worker.arq_worker``) the job is
      queued there; otherwise it falls back to FastAPI's ``BackgroundTasks``
      so the caller's response isn't blocked on SMTP latency.

    All generated recipient addresses are redacted to ``u***@example.com``
    before they touch a log line or an audit row.
    \"\"\"
    from __future__ import annotations

    import logging
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import settings
    from app.crud.email_delivery import (
        mark_delivery_failed,
        mark_delivery_sent,
        record_delivery,
    )
    from app.email.providers import get_provider
    from app.email.registry import TemplateName
    from app.email.render import render_email
    from app.schemas.email import EmailMessage

    logger = logging.getLogger(__name__)


    def _redact_email(email: str) -> str:
        \"\"\"Return a PII-safe rendering of an email address.

        Examples:
            ``alice@example.com`` → ``a***@example.com``
            ``bob@acme.co``       → ``b***@acme.co``

        Args:
            email: Raw recipient address.

        Returns:
            Redacted form safe to log or persist.
        \"\"\"
        if "@" not in email:
            return "***"
        local, _, domain = email.partition("@")
        first = local[:1] or "u"
        return f"{first}***@{domain}"


    def _build_message(rendered: Any, to: str) -> EmailMessage:
        \"\"\"Assemble an ``EmailMessage`` from rendered content + settings.\"\"\"
        return EmailMessage(
            to=to,
            from_=settings.EMAIL_FROM,
            from_name=settings.EMAIL_FROM_NAME,
            subject=rendered.subject,
            html=rendered.html,
            text=rendered.text,
            reply_to=settings.EMAIL_REPLY_TO or None,
        )


    async def send_email(
        session: AsyncSession,
        *,
        to: str,
        template: TemplateName,
        context: dict[str, Any],
        locale: str | None = None,
        user_id: Any | None = None,
    ) -> Any:
        \"\"\"Render + send an email synchronously, persisting an audit row.

        Args:
            session: Async SQLAlchemy session.
            to: Recipient email address (redacted in the audit row).
            template: Template identifier.
            context: Template render context.
            locale: Preferred locale; defaults to ``settings.EMAIL_DEFAULT_LOCALE``.
            user_id: Optional user UUID for the audit FK.

        Returns:
            The persisted ``EmailDelivery`` row.

        Raises:
            Exception: Whatever the provider raises — after the audit row
                is marked failed.
        \"\"\"
        effective_locale = locale or settings.EMAIL_DEFAULT_LOCALE
        rendered = render_email(template, context, effective_locale)
        redacted = _redact_email(to)
        delivery = await record_delivery(
            session,
            to_email_redacted=redacted,
            template_name=template.value,
            locale=effective_locale,
            provider=settings.EMAIL_PROVIDER,
            user_id=user_id,
        )
        message = _build_message(rendered, to)
        try:
            result = await get_provider().send(message)
        except Exception as exc:  # noqa: BLE001 — provider may raise anything
            logger.warning("email send failed for %s", redacted)
            await mark_delivery_failed(session, delivery.id, str(exc)[:500])
            raise
        await mark_delivery_sent(session, delivery.id, result.id)
        return delivery


    async def enqueue_email(
        session: AsyncSession,
        *,
        to: str,
        template: TemplateName,
        context: dict[str, Any],
        locale: str | None = None,
        user_id: Any | None = None,
    ) -> Any:
        \"\"\"Fire-and-forget email send, off the caller's critical path.

        When the arq worker is available (``app.worker.arq_worker`` with
        an ``ArqRedis`` pool) the send is enqueued there.  Otherwise the
        helper awaits ``send_email`` directly — in that case the caller
        is encouraged to wrap the call in ``BackgroundTasks`` at the
        route layer.

        Args:
            session: Async SQLAlchemy session.
            to: Recipient email address.
            template: Template identifier.
            context: Template render context.
            locale: Preferred locale.
            user_id: Optional user UUID.

        Returns:
            The persisted ``EmailDelivery`` row (pending or sent).
        \"\"\"
        try:
            from app.worker.arq_worker import get_arq_pool  # type: ignore
        except ImportError:
            return await send_email(
                session,
                to=to,
                template=template,
                context=context,
                locale=locale,
                user_id=user_id,
            )
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "send_email_job",
            to=to,
            template=template.value,
            context=context,
            locale=locale,
            user_id=str(user_id) if user_id else None,
        )
        return None
""")


_EMAIL_PROVIDERS_INIT_TEMPLATE = textwrap.dedent("""\
    \"\"\"Email provider selector — picks an adapter based on settings.

    The selector reads ``settings.EMAIL_PROVIDER`` on every call so
    operators can flip providers at runtime via env var without
    restarting the app.  Third-party SDKs (``resend``, ``postmark``)
    are imported LAZILY inside each adapter's ``send()`` method.
    \"\"\"
    from __future__ import annotations

    from app.core.config import settings
    from app.email.providers.base import EmailProvider
    from app.email.providers.postmark import PostmarkProvider
    from app.email.providers.resend import ResendProvider
    from app.email.providers.smtp import SMTPProvider


    def get_provider() -> EmailProvider:
        \"\"\"Return the provider adapter matching ``settings.EMAIL_PROVIDER``.

        Returns:
            A provider instance implementing the ``EmailProvider`` protocol.

        Raises:
            ValueError: If ``settings.EMAIL_PROVIDER`` is unknown.
        \"\"\"
        name = (settings.EMAIL_PROVIDER or "resend").lower()
        if name == "resend":
            return ResendProvider()
        if name == "postmark":
            return PostmarkProvider()
        if name == "smtp":
            return SMTPProvider()
        raise ValueError(
            f"unknown EMAIL_PROVIDER {name!r}; expected resend|postmark|smtp"
        )


    __all__ = ["EmailProvider", "get_provider"]
""")


_EMAIL_PROVIDER_BASE_TEMPLATE = textwrap.dedent("""\
    \"\"\"Email provider protocol — the minimal contract all adapters implement.\"\"\"
    from __future__ import annotations

    from typing import Protocol

    from app.schemas.email import EmailMessage, EmailResult


    class EmailProvider(Protocol):
        \"\"\"Abstract provider interface.

        Implementations must be stateless and safe to instantiate on
        every ``get_provider()`` call — construction should NOT perform
        network I/O or import third-party SDKs.  Those side-effects
        belong inside ``send()`` so the app can boot cleanly without
        the SDK installed.
        \"\"\"

        async def send(self, message: EmailMessage) -> EmailResult:
            \"\"\"Send *message* and return the provider's message id.\"\"\"
            ...
""")


_EMAIL_PROVIDER_RESEND_TEMPLATE = textwrap.dedent("""\
    \"\"\"Resend adapter — lazy-imports the ``resend`` SDK on first send.\"\"\"
    from __future__ import annotations

    import logging

    from app.core.config import settings
    from app.schemas.email import EmailMessage, EmailResult

    logger = logging.getLogger(__name__)


    class ResendProvider:
        \"\"\"Resend HTTP API adapter.

        Imports the ``resend`` package lazily so the app boots without
        it.  Uses ``resend.Emails.send`` which wraps the POST /emails
        endpoint.  The API key is read on every call from settings and
        NEVER logged.
        \"\"\"

        async def send(self, message: EmailMessage) -> EmailResult:
            \"\"\"Send *message* via Resend.\"\"\"
            import resend  # local import — app boots without resend

            resend.api_key = settings.RESEND_API_KEY
            payload = {
                "from": (
                    f"{message.from_name} <{message.from_}>"
                    if message.from_name
                    else message.from_
                ),
                "to": [message.to],
                "subject": message.subject,
                "html": message.html,
                "text": message.text,
            }
            if message.reply_to:
                payload["reply_to"] = message.reply_to
            response = resend.Emails.send(payload)
            msg_id = (
                response.get("id") if isinstance(response, dict) else getattr(response, "id", "")
            ) or ""
            return EmailResult(id=str(msg_id), provider="resend")
""")


_EMAIL_PROVIDER_POSTMARK_TEMPLATE = textwrap.dedent("""\
    \"\"\"Postmark adapter — lazy-imports the ``postmark`` SDK on first send.\"\"\"
    from __future__ import annotations

    import logging

    from app.core.config import settings
    from app.schemas.email import EmailMessage, EmailResult

    logger = logging.getLogger(__name__)


    class PostmarkProvider:
        \"\"\"Postmark HTTP API adapter.

        Imports the ``postmarker`` package lazily.  The server token is
        read on every call from settings and NEVER logged.
        \"\"\"

        async def send(self, message: EmailMessage) -> EmailResult:
            \"\"\"Send *message* via Postmark.\"\"\"
            from postmarker.core import PostmarkClient  # local import

            client = PostmarkClient(server_token=settings.POSTMARK_API_KEY)
            from_header = (
                f"{message.from_name} <{message.from_}>"
                if message.from_name
                else message.from_
            )
            response = client.emails.send(
                From=from_header,
                To=message.to,
                Subject=message.subject,
                HtmlBody=message.html,
                TextBody=message.text,
                ReplyTo=message.reply_to or None,
            )
            msg_id = (
                response.get("MessageID") if isinstance(response, dict) else ""
            ) or ""
            return EmailResult(id=str(msg_id), provider="postmark")
""")


_EMAIL_PROVIDER_SMTP_TEMPLATE = textwrap.dedent("""\
    \"\"\"SMTP adapter — uses stdlib ``smtplib``, no third-party deps.\"\"\"
    from __future__ import annotations

    import asyncio
    import logging
    import smtplib
    from email.message import EmailMessage as StdlibEmailMessage

    from app.core.config import settings
    from app.schemas.email import EmailMessage, EmailResult

    logger = logging.getLogger(__name__)


    def _build_mime(message: EmailMessage) -> StdlibEmailMessage:
        \"\"\"Build a stdlib ``EmailMessage`` with HTML + plaintext alternatives.

        Args:
            message: Application-level email payload.

        Returns:
            A MIME multipart/alternative message ready for ``send_message``.
        \"\"\"
        mime = StdlibEmailMessage()
        mime["Subject"] = message.subject
        mime["From"] = (
            f"{message.from_name} <{message.from_}>"
            if message.from_name
            else message.from_
        )
        mime["To"] = message.to
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        return mime


    def _send_sync(mime: StdlibEmailMessage) -> str:
        \"\"\"Open an SMTP connection and send *mime* synchronously.

        Args:
            mime: Pre-built MIME message.

        Returns:
            The SMTP ``Message-ID`` header (or empty string).
        \"\"\"
        host = settings.SMTP_HOST or "localhost"
        port = int(settings.SMTP_PORT or 587)
        with smtplib.SMTP(host, port) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(mime)
        return mime.get("Message-ID", "")


    class SMTPProvider:
        \"\"\"Pure-stdlib SMTP adapter — no third-party dependency.\"\"\"

        async def send(self, message: EmailMessage) -> EmailResult:
            \"\"\"Send *message* via SMTP in a worker thread.\"\"\"
            mime = _build_mime(message)
            msg_id = await asyncio.to_thread(_send_sync, mime)
            return EmailResult(id=str(msg_id), provider="smtp")
""")


_EMAIL_SCHEMAS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Pydantic schemas + internal dataclasses for the email layer.

    ``EmailMessage`` and ``EmailResult`` are plain dataclasses — they
    live on the hot path between renderer and provider and never cross
    the HTTP boundary, so pydantic validation would be pure overhead.
    ``EmailDeliveryPublic`` is a pydantic model that the
    ``GET /email/deliveries/me`` endpoint uses to return a PII-safe
    view of an audit row (the recipient is already redacted in the DB,
    but the schema explicitly drops the ``provider_message_id`` field
    from the public view for good measure).
    \"\"\"
    from __future__ import annotations

    import uuid
    from dataclasses import dataclass
    from datetime import datetime

    from pydantic import BaseModel, ConfigDict, Field


    @dataclass(frozen=True)
    class EmailMessage:
        \"\"\"Internal provider payload.\"\"\"

        to: str
        from_: str
        from_name: str
        subject: str
        html: str
        text: str
        reply_to: str | None = None


    @dataclass(frozen=True)
    class EmailResult:
        \"\"\"Provider response — message id + provider name.\"\"\"

        id: str
        provider: str


    class EmailDeliveryPublic(BaseModel):
        \"\"\"PII-safe public view of an email delivery audit row.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        to_email_redacted: str
        template_name: str
        locale: str
        provider: str
        status: str
        error: str | None = None
        created_at: datetime
        sent_at: datetime | None = None


    class EmailDeliveryListResponse(BaseModel):
        \"\"\"Envelope for GET /email/deliveries/me.\"\"\"

        data: list[EmailDeliveryPublic]
        count: int


    class EmailPreviewRequest(BaseModel):
        \"\"\"Optional body for POST /email/preview.\"\"\"

        template: str
        context: dict = Field(default_factory=dict)
        locale: str = "en"
""")


_EMAIL_CRUD_TEMPLATE = textwrap.dedent("""\
    \"\"\"Async CRUD helpers for the ``email_deliveries`` table.

    Each helper keeps the audit trail consistent with the lifecycle
    ``pending → sent → (delivered | failed)``.  Every transition is
    idempotent.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime, timezone
    from typing import Any

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.email_delivery import EmailDelivery


    async def record_delivery(
        session: AsyncSession,
        *,
        to_email_redacted: str,
        template_name: str,
        locale: str,
        provider: str,
        user_id: Any | None,
    ) -> EmailDelivery:
        \"\"\"Insert a ``pending`` EmailDelivery row.\"\"\"
        delivery = EmailDelivery(
            to_email_redacted=to_email_redacted[:255],
            template_name=template_name[:64],
            locale=locale[:8],
            provider=provider[:32],
            status="pending",
            user_id=user_id,
        )
        session.add(delivery)
        await session.flush()
        return delivery


    async def mark_delivery_sent(
        session: AsyncSession,
        delivery_id: uuid.UUID,
        provider_message_id: str,
    ) -> EmailDelivery | None:
        \"\"\"Transition a delivery to ``sent`` (idempotent).\"\"\"
        delivery = await get_delivery(session, delivery_id)
        if delivery is None or delivery.status == "sent":
            return delivery
        delivery.status = "sent"
        delivery.provider_message_id = (provider_message_id or "")[:255]
        delivery.sent_at = datetime.now(timezone.utc)
        await session.flush()
        return delivery


    async def mark_delivery_failed(
        session: AsyncSession,
        delivery_id: uuid.UUID,
        error: str,
    ) -> EmailDelivery | None:
        \"\"\"Transition a delivery to ``failed`` (idempotent).\"\"\"
        delivery = await get_delivery(session, delivery_id)
        if delivery is None or delivery.status == "failed":
            return delivery
        delivery.status = "failed"
        delivery.error = (error or "")[:500]
        await session.flush()
        return delivery


    async def get_delivery(
        session: AsyncSession,
        delivery_id: uuid.UUID,
    ) -> EmailDelivery | None:
        \"\"\"Return the EmailDelivery row with *delivery_id* or ``None``.\"\"\"
        stmt = select(EmailDelivery).where(EmailDelivery.id == delivery_id)
        return (await session.execute(stmt)).scalar_one_or_none()


    async def list_user_deliveries(
        session: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EmailDelivery], int]:
        \"\"\"Return (rows, total_count) for a user's email deliveries.\"\"\"
        total_stmt = (
            select(func.count())
            .select_from(EmailDelivery)
            .where(EmailDelivery.user_id == user_id)
        )
        total = int((await session.execute(total_stmt)).scalar_one() or 0)
        page_stmt = (
            select(EmailDelivery)
            .where(EmailDelivery.user_id == user_id)
            .order_by(EmailDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, total
""")


_EMAIL_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"HTTP routes for the email layer.

    Endpoints:
        GET /email/preview/{template_name}
            Render a template with the registry's example context and
            return the HTML body as ``text/html``.  **403 in production**
            unless ``settings.EMAIL_PREVIEW_ENABLED_IN_PROD`` is true.
            Intended for designers iterating on templates.

        GET /email/deliveries/me
            Paginated list of the current user's email deliveries
            (PII-safe, recipient already redacted).
    \"\"\"
    from __future__ import annotations

    from fastapi import APIRouter, HTTPException, Query, status
    from fastapi.responses import HTMLResponse

    from app.api.deps import CurrentUser
    from app.core.config import settings
    from app.core.session import SessionDep
    from app.crud.email_delivery import list_user_deliveries
    from app.email.registry import TEMPLATE_EXAMPLE_CONTEXT, TemplateName
    from app.email.render import render_email
    from app.schemas.email import EmailDeliveryListResponse, EmailDeliveryPublic

    router = APIRouter(prefix="/email", tags=["email"])


    def _preview_guard() -> None:
        \"\"\"Raise 403 if preview is disabled in the current environment.\"\"\"
        env = (getattr(settings, "ENVIRONMENT", "") or "").lower()
        if env == "production" and not getattr(
            settings, "EMAIL_PREVIEW_ENABLED_IN_PROD", False
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="email preview is disabled in production",
            )


    def _resolve_template(name: str) -> TemplateName:
        \"\"\"Map a URL slug to a ``TemplateName`` or raise 404.\"\"\"
        try:
            return TemplateName(name)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown template {name!r}",
            ) from exc


    @router.get("/preview/{template_name}", response_class=HTMLResponse)
    async def preview_template(
        template_name: str,
        locale: str = Query(default="en"),
    ) -> HTMLResponse:
        \"\"\"Return the rendered HTML body of a template for dev preview.\"\"\"
        _preview_guard()
        template = _resolve_template(template_name)
        context = dict(TEMPLATE_EXAMPLE_CONTEXT.get(template, {}))
        rendered = render_email(template, context, locale=locale)
        return HTMLResponse(content=rendered.html)


    @router.get("/deliveries/me", response_model=EmailDeliveryListResponse)
    async def list_my_deliveries(
        current_user: CurrentUser,
        session: SessionDep,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> EmailDeliveryListResponse:
        \"\"\"Return the current user's email deliveries, newest first.\"\"\"
        rows, total = await list_user_deliveries(
            session, current_user.id, limit=limit, offset=skip
        )
        data = [EmailDeliveryPublic.model_validate(r) for r in rows]
        return EmailDeliveryListResponse(data=data, count=total)
""")


_EMAIL_DELIVERY_TENANT_COL_TENANTED = (
    '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
    '        Uuid,\n'
    '        ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    '        nullable=True,\n'
    '        index=True,\n'
    '        comment="Tenant owning this delivery record",\n'
    '    )'
)

_EMAIL_DELIVERY_TENANT_COL_PLAIN = (
    '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
    '        Uuid,\n'
    '        nullable=True,\n'
    '        index=True,\n'
    '        comment="Tenant owning this delivery record",\n'
    '    )'
)


_EMAIL_DELIVERY_MODEL_TEMPLATE = textwrap.dedent("""\
    \"\"\"SQLAlchemy model for email delivery audit records.

    The ``email_deliveries`` table persists every send attempt so
    operators can troubleshoot bounces/failures without tailing logs.
    The recipient is REDACTED at write time (``u***@example.com``) so
    a DB dump can never leak PII even if it escapes the operator
    firewall.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import (
        CheckConstraint,
        DateTime,
        ForeignKey,
        Index,
        String,
        Uuid,
        func,
    )
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class EmailDelivery(Base):
        \"\"\"An email send attempt — one row per provider call.

        Attributes:
            id: Internal UUID primary key.
            to_email_redacted: Redacted recipient (e.g. ``a***@example.com``).
            template_name: Logical template name from ``TemplateName``.
            locale: Locale actually used for rendering (post-fallback).
            provider: Provider used (``resend`` / ``postmark`` / ``smtp``).
            provider_message_id: Provider's own message id (populated on
                successful send, used for reconciling webhook events).
            status: Lifecycle status — ``pending`` / ``sent`` / ``failed``.
            error: Truncated error message (max 500 chars) when ``failed``.
            user_id: Optional FK to ``users.id``.
            tenant_id: Optional tenant UUID (FK only when tenants exist).
            created_at: UTC timestamp when the row was inserted.
            sent_at: UTC timestamp when the provider accepted the send.
        \"\"\"

        __tablename__ = "email_deliveries"

        id: Mapped[uuid.UUID] = mapped_column(
            Uuid, primary_key=True, default=uuid.uuid4
        )
        to_email_redacted: Mapped[str] = mapped_column(
            String(255), nullable=False
        )
        template_name: Mapped[str] = mapped_column(
            String(64), nullable=False, index=True
        )
        locale: Mapped[str] = mapped_column(String(8), nullable=False)
        provider: Mapped[str] = mapped_column(String(32), nullable=False)
        provider_message_id: Mapped[str | None] = mapped_column(
            String(255), nullable=True
        )
        status: Mapped[str] = mapped_column(
            String(32), nullable=False, server_default="pending"
        )
        error: Mapped[str | None] = mapped_column(String(500), nullable=True)
        user_id: Mapped[uuid.UUID | None] = mapped_column(
            Uuid,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
    TENANT_PLACEHOLDER
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
        sent_at: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )

        __table_args__ = (
            CheckConstraint(
                "status IN ('pending','sent','delivered','bounced','failed')",
                name="ck_email_deliveries_status",
            ),
            Index(
                "ix_email_deliveries_status_created",
                "status",
                "created_at",
            ),
            Index(
                "ix_email_deliveries_user_created",
                "user_id",
                "created_at",
            ),
        )
""")


_EMAIL_MIGRATION_TENANT_TENANTED = (
    '        sa.Column(\n'
    '            "tenant_id", sa.Uuid(),\n'
    '            sa.ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    '            nullable=True,\n'
    '        ),'
)

_EMAIL_MIGRATION_TENANT_PLAIN = (
    '        sa.Column("tenant_id", sa.Uuid(), nullable=True),'
)


_EMAIL_MIGRATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Add email_deliveries table for transactional email audit trail.

    Revision ID: add_email_templates
    Revises: DOWN_REV
    Create Date: auto-generated by add_email_templates tool
    \"\"\"
    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision = "add_email_templates"
    down_revision = "DOWN_REV"
    branch_labels = None
    depends_on = None


    def _email_delivery_columns() -> list:
        \"\"\"Return the column list for the email_deliveries table.\"\"\"
        return [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("to_email_redacted", sa.String(255), nullable=False),
            sa.Column("template_name", sa.String(64), nullable=False),
            sa.Column("locale", sa.String(8), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("provider_message_id", sa.String(255), nullable=True),
            sa.Column(
                "status", sa.String(32),
                server_default="pending", nullable=False,
            ),
            sa.Column("error", sa.String(500), nullable=True),
            sa.Column(
                "user_id", sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
    TENANT_PLACEHOLDER
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending','sent','delivered','bounced','failed')",
                name="ck_email_deliveries_status",
            ),
        ]


    def _create_email_delivery_indexes() -> None:
        \"\"\"Create all indexes on the email_deliveries table.\"\"\"
        op.create_index(
            "ix_email_deliveries_template_name",
            "email_deliveries", ["template_name"],
        )
        op.create_index(
            "ix_email_deliveries_user_id",
            "email_deliveries", ["user_id"],
        )
        op.create_index(
            "ix_email_deliveries_status_created",
            "email_deliveries", ["status", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_email_deliveries_user_created",
            "email_deliveries", ["user_id", sa.text("created_at DESC")],
        )


    def upgrade() -> None:
        \"\"\"Create the email_deliveries table and all indexes.\"\"\"
        op.create_table("email_deliveries", *_email_delivery_columns())
        _create_email_delivery_indexes()


    def downgrade() -> None:
        \"\"\"Drop the email_deliveries table and its indexes.\"\"\"
        op.drop_index(
            "ix_email_deliveries_user_created", table_name="email_deliveries"
        )
        op.drop_index(
            "ix_email_deliveries_status_created", table_name="email_deliveries"
        )
        op.drop_index(
            "ix_email_deliveries_user_id", table_name="email_deliveries"
        )
        op.drop_index(
            "ix_email_deliveries_template_name", table_name="email_deliveries"
        )
        op.drop_table("email_deliveries")
""")


# ---------------------------------------------------------------------------
# Jinja2 template triples — HTML + plaintext + subject per template.
# These strings are written to disk verbatim.  The ``{{ }}`` blocks inside
# them are Jinja2 placeholders, NOT Python format strings.
# ---------------------------------------------------------------------------

_WELCOME_TEMPLATE_TRIPLE = {
    "subject.txt": "Welcome to {{ app_name }}, {{ user_name }}!\n",
    "html": (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "  <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "background:#f6f7f9; margin:0; padding:24px;\">\n"
        "    <div style=\"max-width:560px; margin:0 auto; background:#ffffff; "
        "border-radius:12px; padding:32px; box-shadow:0 1px 4px rgba(0,0,0,0.06);\">\n"
        "      <h1 style=\"margin:0 0 16px 0; color:#111827; font-size:22px;\">"
        "Welcome, {{ user_name }}!</h1>\n"
        "      <p style=\"color:#374151; font-size:16px; line-height:1.5;\">\n"
        "        Thanks for signing up for {{ app_name | default('our app') }}. "
        "Click the button below to activate your account and get started.\n"
        "      </p>\n"
        "      <p style=\"margin:24px 0;\">\n"
        "        <a href=\"{{ activation_url }}\" "
        "style=\"display:inline-block; background:#2563eb; color:#ffffff; "
        "text-decoration:none; padding:12px 20px; border-radius:8px; "
        "font-weight:600;\">Activate account</a>\n"
        "      </p>\n"
        "      <p style=\"color:#6b7280; font-size:13px;\">\n"
        "        If the button doesn't work, paste this URL into your browser:<br>\n"
        "        <span style=\"word-break:break-all;\">{{ activation_url }}</span>\n"
        "      </p>\n"
        "    </div>\n"
        "  </body>\n"
        "</html>\n"
    ),
    "txt": (
        "Welcome, {{ user_name }}!\n"
        "\n"
        "Thanks for signing up for {{ app_name }}. Activate your account here:\n"
        "{{ activation_url }}\n"
        "\n"
        "If you did not sign up, you can ignore this message.\n"
    ),
}


_PASSWORD_RESET_TEMPLATE_TRIPLE = {
    "subject.txt": "Reset your {{ app_name }} password\n",
    "html": (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "  <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "background:#f6f7f9; margin:0; padding:24px;\">\n"
        "    <div style=\"max-width:560px; margin:0 auto; background:#ffffff; "
        "border-radius:12px; padding:32px; box-shadow:0 1px 4px rgba(0,0,0,0.06);\">\n"
        "      <h1 style=\"margin:0 0 16px 0; color:#111827; font-size:22px;\">"
        "Password reset</h1>\n"
        "      <p style=\"color:#374151; font-size:16px; line-height:1.5;\">\n"
        "        Hi {{ user_name }}, we received a request to reset your password. "
        "This link expires in {{ expires_in_hours }} hours.\n"
        "      </p>\n"
        "      <p style=\"margin:24px 0;\">\n"
        "        <a href=\"{{ reset_url }}\" "
        "style=\"display:inline-block; background:#dc2626; color:#ffffff; "
        "text-decoration:none; padding:12px 20px; border-radius:8px; "
        "font-weight:600;\">Reset password</a>\n"
        "      </p>\n"
        "      <p style=\"color:#6b7280; font-size:13px;\">\n"
        "        If you did not request a reset, you can safely ignore this email — "
        "your current password will continue to work.\n"
        "      </p>\n"
        "    </div>\n"
        "  </body>\n"
        "</html>\n"
    ),
    "txt": (
        "Password reset\n"
        "\n"
        "Hi {{ user_name }},\n"
        "\n"
        "We received a request to reset your password. "
        "This link expires in {{ expires_in_hours }} hours:\n"
        "{{ reset_url }}\n"
        "\n"
        "If you did not request a reset, ignore this email.\n"
    ),
}


_EMAIL_VERIFICATION_TEMPLATE_TRIPLE = {
    "subject.txt": "Verify your email for {{ app_name }}\n",
    "html": (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "  <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "background:#f6f7f9; margin:0; padding:24px;\">\n"
        "    <div style=\"max-width:560px; margin:0 auto; background:#ffffff; "
        "border-radius:12px; padding:32px; box-shadow:0 1px 4px rgba(0,0,0,0.06);\">\n"
        "      <h1 style=\"margin:0 0 16px 0; color:#111827; font-size:22px;\">"
        "Verify your email</h1>\n"
        "      <p style=\"color:#374151; font-size:16px; line-height:1.5;\">\n"
        "        Hi {{ user_name }}, please confirm this is really your email "
        "address by clicking the button below.\n"
        "      </p>\n"
        "      <p style=\"margin:24px 0;\">\n"
        "        <a href=\"{{ verification_url }}\" "
        "style=\"display:inline-block; background:#059669; color:#ffffff; "
        "text-decoration:none; padding:12px 20px; border-radius:8px; "
        "font-weight:600;\">Verify email</a>\n"
        "      </p>\n"
        "    </div>\n"
        "  </body>\n"
        "</html>\n"
    ),
    "txt": (
        "Verify your email\n"
        "\n"
        "Hi {{ user_name }},\n"
        "\n"
        "Please confirm your email address by visiting:\n"
        "{{ verification_url }}\n"
    ),
}


_RECEIPT_TEMPLATE_TRIPLE = {
    "subject.txt": "Your {{ app_name }} receipt for {{ item_name }}\n",
    "html": (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "  <body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "background:#f6f7f9; margin:0; padding:24px;\">\n"
        "    <div style=\"max-width:560px; margin:0 auto; background:#ffffff; "
        "border-radius:12px; padding:32px; box-shadow:0 1px 4px rgba(0,0,0,0.06);\">\n"
        "      <h1 style=\"margin:0 0 16px 0; color:#111827; font-size:22px;\">"
        "Thanks for your purchase</h1>\n"
        "      <p style=\"color:#374151; font-size:16px; line-height:1.5;\">\n"
        "        Hi {{ user_name }}, this is a confirmation for "
        "<strong>{{ item_name }}</strong> — <strong>{{ amount_formatted }}</strong>.\n"
        "      </p>\n"
        "      <p style=\"margin:24px 0;\">\n"
        "        <a href=\"{{ receipt_url }}\" "
        "style=\"display:inline-block; background:#0f172a; color:#ffffff; "
        "text-decoration:none; padding:12px 20px; border-radius:8px; "
        "font-weight:600;\">View full receipt</a>\n"
        "      </p>\n"
        "      <p style=\"color:#6b7280; font-size:13px;\">\n"
        "        Keep this email for your records.\n"
        "      </p>\n"
        "    </div>\n"
        "  </body>\n"
        "</html>\n"
    ),
    "txt": (
        "Thanks for your purchase, {{ user_name }}!\n"
        "\n"
        "Item:   {{ item_name }}\n"
        "Amount: {{ amount_formatted }}\n"
        "\n"
        "Full receipt: {{ receipt_url }}\n"
    ),
}
