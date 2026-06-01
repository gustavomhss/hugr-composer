"""TOOL-114: add_secret_rotation — secret manager abstraction with auto-rotation.

Writes a provider abstraction (Vault / AWS Secrets Manager / env fallback),
dual-key auto-rotation, leak-detector response middleware, startup validation
that refuses to boot on missing/default secrets, and a
``scripts/rotate_secrets.py`` CLI.

``hvac`` (Vault) and ``boto3`` (AWS SM) are imported lazily inside their
provider classes so the application can boot without either library
installed.

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.

The tool is idempotent: a second run detects ``SecretProvider`` in
``app/core/secret_rotation.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_secret_rotation",
    "description": (
        "Add a secret manager abstraction (Vault/AWS SM/env), auto-rotation with "
        "dual-key windows, log-based leak detection, and startup validation."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_secret_rotation",
}


def add_secret_rotation(inp: ToolInput) -> ToolResult:
    """Add a secret-rotation scaffold to a FastAPI project.

    Ships the secret-manager abstraction (Vault/AWS SM/env), dual-key rotation
    windows, log-based leak detection and startup validation — but the pieces
    are NOT auto-active: LeakDetectorMiddleware is not auto-wired, EnvSecret
    provider.set() only mutates the running process (not persisted), and you
    must call the startup validator from your lifespan for the refuse-to-boot
    guarantee. See ``warnings`` and complete the wiring before production.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    rotation_file = app_dir / "core" / "secret_rotation.py"

    if rotation_file.exists() and "SecretProvider" in rotation_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SecretProvider already present — skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: app/core/secret_rotation.py, "
                "app/middleware/leak_detector.py, scripts/rotate_secrets.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    rotation_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "secret_rotation_core.py.tmpl", dest=rotation_file, substitutions={})
    files_created.append(str(rotation_file))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    leak_file = middleware_dir / "leak_detector.py"
    render_to(_HERE, "leak_detector.py.tmpl", dest=leak_file, substitutions={})
    files_created.append(str(leak_file))

    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    cli_file = scripts_dir / "rotate_secrets.py"
    render_to(_HERE, "rotate_secrets_cli.py.tmpl", dest=cli_file, substitutions={})
    files_created.append(str(cli_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_ms(start),
                )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Secret rotation installed: provider abstraction (Vault/AWS SM/env),",
            "dual-key auto-rotation window, log-based leak detector middleware,",
            "startup validation, and scripts/rotate_secrets.py CLI.",
            "Vault and boto3 imports are lazy — app boots without them.",
            "⚠ LeakDetectorMiddleware IS NOT auto-wired into app/main.py — you must call "
            "app.add_middleware(LeakDetectorMiddleware) yourself for response scrubbing to apply.",
            "⚠ EnvSecretProvider.set() only mutates the running process — it is NOT "
            "persisted to your deployment store (Helm/Terraform/SOPS). Restarting the "
            "process loses the rotation.",
            "⚠ The startup validator is OPT-IN — you must call validate_secrets_at_startup() "
            "from your lifespan handler for the refuse-to-boot guarantee to apply.",
        ],
        next_steps=[
            "Set SECRET_PROVIDER=vault|aws|env in .env.",
            "If using Vault: set VAULT_URL and VAULT_TOKEN.",
            "Call validate_secrets_at_startup() in your FastAPI lifespan.",
            "Register LeakDetectorMiddleware in app/main.py.",
            "Run: python scripts/rotate_secrets.py --help",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject secret rotation settings into the Settings class body."""
    src = config_file.read_text()
    if "SECRET_PROVIDER" in src:
        return
    block = (
        "\n"
        "    # --- Secret rotation — added by add_secret_rotation tool ---\n"
        '    SECRET_PROVIDER: str = "env"  # vault | aws | env\n'
        '    VAULT_URL: str = ""\n'
        '    VAULT_TOKEN: str = ""\n'
        "    SECRET_ROTATION_INTERVAL_H: int = 24\n"
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


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure hvac and boto3 stubs are noted in requirements.txt."""
    src = requirements_file.read_text()
    additions: list[str] = []
    if "hvac" not in src:
        additions.append("hvac>=2.3.0  # optional: Vault provider")
    if "boto3" not in src:
        additions.append("boto3>=1.35.0  # optional: AWS Secrets Manager provider")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_secret_rotation_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_secret_rotation_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
