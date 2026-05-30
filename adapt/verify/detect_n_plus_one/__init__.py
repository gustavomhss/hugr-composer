"""TOOL-028: detect_n_plus_one — instrument a FastAPI project for N+1 query detection.

Writes an ASGI middleware that tracks SQLAlchemy queries per request via a
``ContextVar`` (async-safe), a ``@max_queries`` decorator for per-route budgets,
a ``.nplusone-budgets.yaml`` baseline, a pytest conftest plugin, and a GitHub
Actions CI workflow.

The tool is idempotent: a second run on an already-patched project detects the
``QueryCounterMiddleware`` fingerprint and returns ``status="no_op"``.

Honesty (WP-14 §11): the middleware counts every SQL query issued via the
SQLAlchemy event listener — there is NO sampling. However, the listener only
fires for the engines on which ``install_listener`` is called, and the
middleware itself activates only when ``NPLUSONE_ENABLED=1``. ``warnings`` is
worded as "detects N+1 patterns when active", not "catches all N+1".

Note (read-only invariant): this tool patches ``app/main.py`` to register the
middleware conditionally. That patch is gated by an env var (off by default)
so production behavior is unchanged, but the tool DOES write into product
code (``app/main.py``, ``app/core/``, ``app/api/middleware/``). This is
existing behavior preserved verbatim from the legacy flat module — see
WP-14 §3 "Out of scope: behavior changes". The warnings string reflects this.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_detect_n_plus_one",
    "description": "Detect N+1 query patterns in SQLAlchemy ORM code.",
    "tags": ["verify"],
    "entry": "detect_n_plus_one",
}


def detect_n_plus_one(inp: ToolInput) -> ToolResult:
    """Instrument a FastAPI project with N+1 query detection."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    from adapt.contracts.prerequisites import Prereq, check_prerequisites

    prereq_errors = check_prerequisites(inp.project_dir, Prereq.BASE_MODEL)
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    app_dir = project / "app"

    middleware_file = app_dir / "api" / "middleware" / "query_counter.py"
    if middleware_file.exists() and "QueryCounterMiddleware" in middleware_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["QueryCounterMiddleware already present — N+1 detection already enabled."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would instrument project with N+1 query detection."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    listener_file = app_dir / "core" / "query_listener.py"
    render_to(_HERE, "query_listener.py.tmpl", dest=listener_file, substitutions={})
    files_created.append(str(listener_file))

    middleware_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    decorator_file = app_dir / "core" / "nplusone.py"
    render_to(_HERE, "decorator.py.tmpl", dest=decorator_file, substitutions={})
    files_created.append(str(decorator_file))

    budgets_file = project / ".nplusone-budgets.yaml"
    if not budgets_file.exists():
        render_to(_HERE, "budgets.yaml.tmpl", dest=budgets_file, substitutions={})
        files_created.append(str(budgets_file))

    conftest_file = project / "tests" / "conftest_nplusone.py"
    conftest_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "conftest.py.tmpl", dest=conftest_file, substitutions={})
    files_created.append(str(conftest_file))

    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    ci_file = ci_dir / "nplusone.yml"
    if not ci_file.exists():
        render_to(_HERE, "ci_workflow.yml.tmpl", dest=ci_file, substitutions={})
        files_created.append(str(ci_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # Phase-5 emitted test (P1 #15)
    emitted_test = project / "tests" / "test_detect_n_plus_one_emitted.py"
    if not emitted_test.exists():
        render_to(_HERE, "test_emitted.py.tmpl", dest=emitted_test, substitutions={})
        files_created.append(str(emitted_test))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "N+1 detection uses ContextVar — safe for async FastAPI + AsyncSession.",
            "Middleware active only when NPLUSONE_ENABLED=1 env var is set.",
            "Per-route budgets committed to .nplusone-budgets.yaml.",
        ],
        warnings=[
            "Advisory check: every SQL query issued via SQLAlchemy event listeners is "
            "counted while NPLUSONE_ENABLED=1; queries on engines without install_listener "
            "called are NOT counted. The middleware only warns by default (mode=warn) — "
            "set NPLUSONE_MODE=fail_fast to raise on threshold breach. Patches app/main.py "
            "to register middleware conditionally."
        ],
        next_steps=[
            "Set NPLUSONE_ENABLED=1 in .env (or CI env) to activate detection.",
            "Add conftest_nplusone.py to your conftest.py: 'from tests.conftest_nplusone import *'",
            "Annotate high-query routes with @max_queries(N) from app.core.nplusone.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_main(main_file: Path) -> None:
    """Patch app/main.py to register QueryCounterMiddleware when NPLUSONE_ENABLED."""
    src = main_file.read_text()
    if "QueryCounterMiddleware" in src or "nplusone" in src.lower():
        return

    middleware_block = render(_HERE, "main_patch.py.tmpl", {})

    if "app = FastAPI(" in src:
        open_pos = src.find("app = FastAPI(") + len("app = FastAPI(")
        depth = 1
        pos = open_pos
        while pos < len(src) and depth > 0:
            if src[pos] == "(":
                depth += 1
            elif src[pos] == ")":
                depth -= 1
            pos += 1
        insert_after = src.find("\n", pos)
        if insert_after == -1:
            insert_after = len(src)
        src = src[:insert_after] + middleware_block + src[insert_after:]
    else:
        src = src + middleware_block

    main_file.write_text(src)


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
