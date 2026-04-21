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

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

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


_GLUE = '''\
"""Wire an exponential-backoff retry policy into the FastAPI app.

Delegates to the primitive + FastAPI adapter copied under `core/venous/`
by the `add_retry_budget` tool. Re-emitted idempotently on subsequent runs.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from core.venous._adapters.fastapi.RetryPolicyAdapter import (
    budget,
    install,
    policy_dep,
)


def install_retry_policy(app: FastAPI) -> None:
    """Attach a shared retry policy to *app.state.retry_policy*."""
    install(
        app,
        max_attempts=int(os.getenv("RETRY_MAX_ATTEMPTS", "3")),
        initial_interval_ms=int(os.getenv("RETRY_INITIAL_MS", "100")),
        multiplier=float(os.getenv("RETRY_MULTIPLIER", "2.0")),
        max_interval_ms=int(os.getenv("RETRY_MAX_INTERVAL_MS", "30000")),
        jitter=float(os.getenv("RETRY_JITTER", "1.0")),
        budget_ratio=float(os.getenv("RETRY_BUDGET_RATIO", "0.1")),
    )


__all__ = ["budget", "install_retry_policy", "policy_dep"]
'''


def add_retry_budget(inp: ToolInput) -> ToolResult:
    """Add a retry policy by delegating to the shipped primitive + adapter."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "retry.py"

    if glue_file.exists() and "RetryPolicyAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Retry policy already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy RetryPolicy primitive + FastAPI adapter "
                "and write app/retry.py calling RetryPolicyAdapter.install(app, ...)."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.RetryPolicy"],
        adapters=["core.venous._adapters.fastapi.RetryPolicyAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    glue_file.write_text(_GLUE)
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
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    """Return elapsed ms since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
