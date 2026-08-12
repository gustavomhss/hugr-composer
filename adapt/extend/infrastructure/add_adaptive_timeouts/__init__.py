"""TOOL-096: add_adaptive_timeouts — TimeoutBudget-based request deadlines.

Follows the CONTRACT §B1.0 + §B1.0.1 pattern:

1. Copy the framework-agnostic primitive
   ``core.venous.resiliency.TimeoutBudget`` into the generated project.
2. Emit a thin ``app/resilience/timeouts.py`` (≤ 20 logic lines) glue file
   that instantiates a ``MonotonicTimeoutBudget`` per request and runs the
   handler inside ``asyncio.wait_for(..., timeout=budget.remaining_ms/1000)``.
3. Emit a per-dependency ``AdaptiveTimeout`` / ``TimeoutRegistry`` helper
   that records observed latency and auto-adjusts to p99 * 1.5 — this is
   an application-level policy layered on top of the primitive.

The tool is idempotent: a second run detects the primitive's
``MonotonicTimeoutBudget`` import in ``app/resilience/timeouts.py`` and
returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_adaptive_timeouts",
    "description": (
        "Copy TimeoutBudget primitive into the project and wire a thin "
        "app/resilience/timeouts.py + ASGI middleware that runs requests "
        "inside asyncio.wait_for(..., timeout=budget.remaining_ms/1000)."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_adaptive_timeouts",
    "imports_primitives": [
        "core.venous.resiliency.TimeoutBudget",
    ],
    "imports_adapters": (),
}


def add_adaptive_timeouts(inp: ToolInput) -> ToolResult:
    """Add adaptive timeouts by delegating to the shipped TimeoutBudget primitive."""
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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

    project = Path(inp.project_dir)
    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    resilience_dir = app_dir / "resilience"
    timeouts_glue = resilience_dir / "timeouts.py"

    if timeouts_glue.exists() and "MonotonicTimeoutBudget" in timeouts_glue.read_text():
        return ToolResult(
            status="no_op",
            notes=["TimeoutBudget primitive already wired via app/resilience/timeouts.py."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy TimeoutBudget primitive and write "
                "app/resilience/timeouts.py + adaptive_timeout.py + timeout_registry.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.resiliency.TimeoutBudget"],
        adapters=[],
    )
    files_created.append(manifest.path)

    files_modified: list[str] = []

    resilience_dir.mkdir(parents=True, exist_ok=True)
    resilience_init = resilience_dir / "__init__.py"
    if not resilience_init.exists():
        resilience_init.write_text('"""Resilience patterns package."""\n')
        files_created.append(str(resilience_init))

    render_to(_HERE, "timeouts_glue.py.tmpl", dest=timeouts_glue, substitutions={})
    files_created.append(str(timeouts_glue))

    registry_file = resilience_dir / "timeout_registry.py"
    render_to(_HERE, "timeout_registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))

    adaptive_file = resilience_dir / "adaptive_timeout.py"
    render_to(_HERE, "adaptive_timeout.py.tmpl", dest=adaptive_file, substitutions={})
    files_created.append(str(adaptive_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    glue_loc = _count_logic_lines(timeouts_glue.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Primary glue {timeouts_glue} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_elapsed_ms(start),
        )

    _emit_project_test(project, files_created)

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
            "Shipped primitive: core.venous.resiliency.TimeoutBudget.",
            "Glue: app/resilience/timeouts.py wires MonotonicTimeoutBudget + asyncio.wait_for.",
            "app/resilience/adaptive_timeout.py adds per-dependency p99*1.5 stats "
            "(application layer — delegates deadlines to the primitive).",
            "TimeoutRegistry tracks each dependency independently (DB, Redis, Stripe, etc.).",
            "Config: ADAPTIVE_TIMEOUT_ENABLED, FLOOR_MS=100, CEILING_MS=10000, WINDOW_SIZE=100.",
        ],
        next_steps=[
            "Set ADAPTIVE_TIMEOUT_ENABLED=true in .env to activate.",
            "Install middleware: install_adaptive_timeouts(app) in main.py.",
            "Decorate downstream calls: @adaptive_timeout('payment_service')",
            "Catch asyncio.TimeoutError / TimeoutBudgetExpired for graceful degradation.",
            "Monitor TimeoutRegistry.get_stats() for per-service timeout values.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Add ADAPTIVE_TIMEOUT_* fields to ``app/core/config.py`` Settings class."""
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("ADAPTIVE_TIMEOUT_ENABLED", "ADAPTIVE_TIMEOUT_ENABLED: bool = False"),
            ("ADAPTIVE_TIMEOUT_FLOOR_MS", "ADAPTIVE_TIMEOUT_FLOOR_MS: float = 100.0"),
            ("ADAPTIVE_TIMEOUT_CEILING_MS", "ADAPTIVE_TIMEOUT_CEILING_MS: float = 10000.0"),
            ("ADAPTIVE_TIMEOUT_WINDOW_SIZE", "ADAPTIVE_TIMEOUT_WINDOW_SIZE: int = 100"),
        ],
    )


def _count_logic_lines(source: str) -> int:
    """Count executable logic lines in a rendered glue file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            start = node.body[0].lineno
            end = node.end_lineno or start
            loc += end - start + 1
    return loc


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_adaptive_timeouts_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_adaptive_timeouts_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


