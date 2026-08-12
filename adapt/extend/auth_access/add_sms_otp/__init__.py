"""TOOL-076: add_sms_otp — SMS OTP authentication via Twilio/Vonage.

Orchestration only. Emitted code lives in ``templates/*.py.tmpl``.

Generates all files required for SMS-based one-time password authentication:
an ``OtpCode`` SQLAlchemy model (phone, code, expires_at, verified),
an ``SmsOtpService`` class with lazy Twilio import, Pydantic schemas, and
two route handlers: ``POST /auth/sms/send`` and ``POST /auth/sms/verify``.

Rate limiting: maximum 5 OTP requests per phone per hour enforced via the
OtpCode table (no Redis required). Codes expire after OTP_EXPIRY_SECONDS.

Idempotent: a second run detects the ``OtpCode`` model fingerprint and
returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_auth_add_sms_otp",
    "description": (
        "Add SMS OTP authentication via Twilio/Vonage with rate limiting to a FastAPI project."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_sms_otp",
    "imports_primitives": [],
    "imports_adapters": [],

}

_NOTES_SUCCESS = [
    "SMS OTP via Twilio (default) or Vonage (SMS_PROVIDER=vonage).",
    "twilio SDK imported lazily inside send_sms — not required at boot.",
    "Rate limit: max 5 OTPs per phone per hour (DB-enforced, no Redis).",
    "OTP codes expire after OTP_EXPIRY_SECONDS (default: 300).",
    "OTP_LENGTH configures code digit count (default: 6).",
    "Phone numbers stored in E.164 format.",
]
_NEXT_STEPS = [
    "pip install twilio  # or vonage",
    "Add SMS_PROVIDER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
    "TWILIO_FROM_NUMBER, OTP_LENGTH, OTP_EXPIRY_SECONDS to settings.",
    "alembic upgrade head",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_sms_otp(inp: ToolInput) -> ToolResult:
    """Add SMS OTP authentication to a FastAPI project."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    model_file = app_dir / "models" / "otp_code.py"
    if model_file.exists() and "OtpCode" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["OtpCode model already present — SMS OTP auth already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create SMS OTP files (Twilio/Vonage).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    render_to(_HERE, "model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))
    _patch_models_init(app_dir / "models" / "__init__.py", [("otp_code", "OtpCode")])

    sms_otp_file = app_dir / "auth" / "sms_otp.py"
    render_to(_HERE, "sms_otp_service.py.tmpl", dest=sms_otp_file, substitutions={})
    files_created.append(str(sms_otp_file))

    auth_init = app_dir / "auth" / "__init__.py"
    if not auth_init.exists():
        auth_init.parent.mkdir(parents=True, exist_ok=True)
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    schema_file = app_dir / "schemas" / "otp.py"
    render_to(_HERE, "schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    routes_file = app_dir / "api" / "routes" / "sms_auth.py"
    render_to(_HERE, "routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0076_add_sms_otp.py"
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=mig_file,
            substitutions={"down_rev": down_rev},
        )
        files_created.append(str(mig_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        if str(config_file) not in files_modified:
            files_modified.append(str(config_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
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


def _patch_config(config_file: Path) -> None:
    """Inject SMS OTP config fields into Settings class idempotently."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("SMS_PROVIDER", 'SMS_PROVIDER: str = "twilio"'),
            ("TWILIO_ACCOUNT_SID", 'TWILIO_ACCOUNT_SID: str = ""'),
            ("TWILIO_AUTH_TOKEN", 'TWILIO_AUTH_TOKEN: str = ""'),
            ("TWILIO_FROM_NUMBER", 'TWILIO_FROM_NUMBER: str = ""'),
            ("OTP_LENGTH", "OTP_LENGTH: int = 6"),
            ("OTP_EXPIRY_SECONDS", "OTP_EXPIRY_SECONDS: int = 300"),
            ("OTP_RATE_LIMIT_MAX", "OTP_RATE_LIMIT_MAX: int = 5"),
            ("OTP_RATE_LIMIT_WINDOW_SECONDS", "OTP_RATE_LIMIT_WINDOW_SECONDS: int = 3600"),
        ],
    )


def _patch_routes_init(routes_init: Path) -> None:
    """Register sms_auth router in app/routes/__init__.py idempotently."""
    src = routes_init.read_text()
    import_line = "from app.api.routes.sms_auth import router as sms_auth_router"
    include_line = "api_router.include_router(sms_auth_router)"
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


