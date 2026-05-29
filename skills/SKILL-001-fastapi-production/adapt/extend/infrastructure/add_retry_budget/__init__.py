"""TOOL-098: add_retry_budget — exponential-backoff retry policy with budget.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy ``core.venous.resiliency.RetryPolicy`` into the project.
2. Copy the FastAPI adapter ``RetryPolicyAdapter``.
3. Emit ``app/retry.py`` (≤ 20-line glue) calling
   ``RetryPolicyAdapter.install(app, ...)``.

Idempotent: a second run detects ``RetryPolicyAdapter`` in the glue
and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_retry_budget",
    "description": (
        "Copy RetryPolicy primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/retry.py caller."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_retry_budget",
    "imports_primitives": [
        "core.venous.resiliency.RetryPolicy",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.RetryPolicyAdapter",
    ],
}


def add_retry_budget(inp: ToolInput) -> ToolResult:
    """Add a retry policy by delegating to the shipped primitive + adapter."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            notes=["Generate a base project first via fastapi_generate_project(...)."],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "retry.py"

    if glue_file.exists() and "RetryPolicyAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Retry policy already wired via the FastAPI adapter."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy RetryPolicy primitive + FastAPI adapter "
                "and write app/retry.py calling RetryPolicyAdapter.install(app, ...)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.RetryPolicy"],
        adapters=["core.venous._adapters.fastapi.RetryPolicyAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "retry_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    files_modified: list[str] = []
    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and "RETRY_MAX_ATTEMPTS" not in config_file.read_text():
        from adapt.contracts.config_patcher import patch_settings_fields

        patch_settings_fields(
            config_file,
            fields=[
                ("RETRY_MAX_ATTEMPTS", "RETRY_MAX_ATTEMPTS: int = 3"),
                ("RETRY_INITIAL_MS", "RETRY_INITIAL_MS: int = 100"),
                ("RETRY_MULTIPLIER", "RETRY_MULTIPLIER: float = 2.0"),
                ("RETRY_MAX_INTERVAL_MS", "RETRY_MAX_INTERVAL_MS: int = 30_000"),
                ("RETRY_JITTER", "RETRY_JITTER: float = 1.0"),
                ("RETRY_BUDGET_RATIO", "RETRY_BUDGET_RATIO: float = 0.1"),
            ],
        )
        files_modified.append(str(config_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitive: core.venous.resiliency.RetryPolicy.",
            "Shipped adapter: core.venous._adapters.fastapi.RetryPolicyAdapter.",
            "Wrote app/retry.py — call install_retry_policy(app) from main.py.",
            "Retries enforce idempotency + trailing-window budget + TimeoutBudget deadlines.",
        ],
        next_steps=[
            "Import install_retry_policy in app/main.py and invoke it after FastAPI().",
            "Use `Depends(policy_dep)` on routes; call `await p.execute(fn, idempotent=True)`.",
            "Set RETRY_* in .env to override defaults (max_attempts=3, budget_ratio=0.1).",
        ],
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_retry_budget_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_retry_budget_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
