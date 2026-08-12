"""TOOL-111: add_runtime_sentinel — RASP injection-detection middleware for FastAPI.

Migrated to per-tool directory + externalized templates (WP-02a).

Generates:
  - ``app/middleware/runtime_sentinel.py`` — RASP middleware + InjectionDetector
  - ``app/core/sentinel_registry.py``       — AttackPatternRegistry + SecurityEvent
  - patches ``app/core/config.py``          — SENTINEL_ENABLED, SENTINEL_MODE, SENTINEL_ALLOWED_HOSTS

Covers SQL/command/SSRF injection with regex-based detection and a learning
→ enforcing mode transition. Tool is idempotent: a second run detects
``RuntimeSentinelMiddleware`` in the middleware file and returns
``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_runtime_sentinel",
    "description": (
        "Add RASP middleware with SQL/command/SSRF injection detection, "
        "attack pattern registry, and learning→enforcing mode transition."
    ),
    "tags": ["extend", "infrastructure", "security", "rasp"],
    "entry": "add_runtime_sentinel",
    "imports_primitives": [],
    "imports_adapters": [],

}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_runtime_sentinel(inp: ToolInput) -> ToolResult:
    """Add runtime sentinel RASP middleware to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
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

    files_created: list[str] = list(scaffolded)

    # --- Idempotency guard ---------------------------------------------------
    middleware_dir = project / "app" / "middleware"
    sentinel_file = middleware_dir / "runtime_sentinel.py"
    if sentinel_file.exists() and "RuntimeSentinelMiddleware" in sentinel_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "RuntimeSentinelMiddleware already present — runtime sentinel already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/runtime_sentinel.py",
                "[dry_run] Would create app/core/sentinel_registry.py",
                "[dry_run] Would patch app/core/config.py with SENTINEL settings",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: middleware package ------------------------------------------
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_init = middleware_dir / "__init__.py"
    if not middleware_init.exists():
        middleware_init.write_text('"""Middleware package."""\n')
        files_created.append(str(middleware_init))

    # --- Step 2: sentinel_registry.py + runtime_sentinel.py via templates ---
    registry_file = project / "app" / "core" / "sentinel_registry.py"
    (project / "app" / "core").mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "sentinel_registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))

    render_to(_HERE, "runtime_sentinel.py.tmpl", dest=sentinel_file, substitutions={})
    files_created.append(str(sentinel_file))

    # --- Step 3: patch config.py ---------------------------------------------
    config_file = project / "app" / "core" / "config.py"
    config_notes: list[str] = []
    if config_file.exists():
        from adapt.contracts.config_patcher import PatchResult

        patch_outcome = _patch_config(config_file)
        if patch_outcome is PatchResult.APPLIED:
            files_modified.append(str(config_file))
        elif patch_outcome is PatchResult.TARGET_MISSING:
            config_notes.append(
                "config.py: no `class Settings` shape found — "
                "SENTINEL_* fields were appended at module level."
            )
        elif patch_outcome is PatchResult.SYNTAX_ERROR:
            return ToolResult(
                status="error",
                error="app/core/config.py has a syntax error — refusing to patch.",
                execution_time_ms=_elapsed_ms(start),
            )

    # --- Step 4: emit project test (P1 #15) ---------------------------------
    _emit_project_test(project, files_created)

    # --- Step 5: ast.parse validation loop -----------------------------------
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
        notes=[
            "Runtime sentinel RASP middleware added.",
            "InjectionDetector: SQL (tautology/UNION/stacked/comment), command (metacharacters), SSRF (allow-list).",
            "AttackPatternRegistry: records SecurityEvent per attack type with timestamps.",
            "Learning mode: logs detections without blocking. There is NO auto-promotion "
            "timer — switching to enforcing is manual (set SENTINEL_MODE=enforcing) after a "
            "baseline you choose (~24h recommended).",
            "Config: SENTINEL_ENABLED, SENTINEL_MODE (learning/enforcing), SENTINEL_ALLOWED_HOSTS.",
            "Register RuntimeSentinelMiddleware in app/main.py lifespan or add_middleware().",
            *config_notes,
        ],
        next_steps=[
            "Register middleware in app/main.py: app.add_middleware(RuntimeSentinelMiddleware)",
            "Set SENTINEL_ENABLED=true, SENTINEL_MODE=learning in .env",
            "After 24h learning period, set SENTINEL_MODE=enforcing",
            "Set SENTINEL_ALLOWED_HOSTS to comma-separated allowed outbound hosts",
            "Review sentinel events in logs: look for SENTINEL_ATTACK entries",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# In-place patchers
# ---------------------------------------------------------------------------


def _patch_config(config_file: Path):  # type: ignore[no-untyped-def]
    """Inject sentinel settings into ``app/core/config.py`` Settings class."""
    from adapt.contracts.config_patcher import patch_settings_fields

    return patch_settings_fields(
        config_file,
        fields=[
            ("SENTINEL_ENABLED", "SENTINEL_ENABLED: bool = True"),
            ("SENTINEL_MODE", 'SENTINEL_MODE: str = "learning"'),
            ("SENTINEL_ALLOWED_HOSTS", 'SENTINEL_ALLOWED_HOSTS: str = ""'),
        ],
    )


# ---------------------------------------------------------------------------
# Emitted test (P1 #15)
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_runtime_sentinel_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_runtime_sentinel_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


