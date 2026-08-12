"""TOOL-124: add_api_fuzzer — schema-aware adversarial fuzzing for FastAPI.

Generates an ``APIFuzzer`` that reads the OpenAPI schema, builds adversarial
inputs per field type (boundary ints, unicode edge cases, SQL payloads, XSS
vectors, empty/null/huge strings), hits each endpoint N times, and reports
any non-JSON 5xx/timeout/crash results.  No external dependencies required.

Idempotent: a second run detects ``APIFuzzer`` in
``app/fuzzer/__init__.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_testing_add_api_fuzzer",
    "description": (
        "Add schema-aware API fuzzing: APIFuzzer reads OpenAPI schema, generates adversarial "
        "inputs per field type (boundary ints, unicode, SQL payloads, XSS vectors, empty/null/"
        "huge strings). FuzzRunner hits each endpoint N times, reports non-JSON 5xx/timeout/"
        "crash. scripts/run_fuzz.py CLI. Config: FUZZ_ITERATIONS, FUZZ_TIMEOUT_S, "
        "FUZZ_EXCLUDE_PATHS. No external deps."
    ),
    "tags": ["extend", "testing_tools"],
    "entry": "add_api_fuzzer",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_api_fuzzer(inp: ToolInput) -> ToolResult:
    """Add schema-aware API fuzzing to a FastAPI project.

    Writes ``app/fuzzer/`` package and ``scripts/run_fuzz.py``, patches
    ``app/core/config.py`` with fuzz knobs.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
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
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    project = Path(inp.project_dir)
    app_dir = project / "app"

    fuzzer_init = app_dir / "fuzzer" / "__init__.py"
    if fuzzer_init.exists() and "APIFuzzer" in fuzzer_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["APIFuzzer already present — API fuzzer already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/fuzzer/ package with APIFuzzer, generators, runner.",
                "[dry_run] Would create scripts/run_fuzz.py CLI.",
                "[dry_run] Would patch app/core/config.py with fuzz config fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    fuzzer_dir = app_dir / "fuzzer"
    fuzzer_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "fuzzer_init.py.tmpl", dest=fuzzer_init, substitutions={})
    files_created.append(str(fuzzer_init))

    render_to(
        _HERE, "fuzzer_generators.py.tmpl", dest=fuzzer_dir / "generators.py", substitutions={}
    )
    files_created.append(str(fuzzer_dir / "generators.py"))

    render_to(_HERE, "fuzzer_runner.py.tmpl", dest=fuzzer_dir / "runner.py", substitutions={})
    files_created.append(str(fuzzer_dir / "runner.py"))

    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "run_fuzz_cli.py.tmpl", dest=scripts_dir / "run_fuzz.py", substitutions={})
    files_created.append(str(scripts_dir / "run_fuzz.py"))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
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

    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_api_fuzzer_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_api_fuzzer_emitted.py.tmpl", dest=emitted, substitutions={})
        files_created.append(str(emitted))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "API fuzzer enabled: APIFuzzer reads OpenAPI schema from /openapi.json.",
            "Generators cover: boundary ints, unicode edge cases, SQL payloads, XSS vectors, "
            "empty/null/huge strings (1 MB).",
            "FuzzRunner hits each discovered endpoint N times and collects non-JSON 5xx/timeout.",
            "Zero external dependencies — pure Python stdlib + httpx (already in requirements).",
            "Run: python scripts/run_fuzz.py --base-url http://localhost:8000",
        ],
        next_steps=[
            "Set FUZZ_ITERATIONS in .env (default: 10 per endpoint).",
            "Set FUZZ_TIMEOUT_S in .env (default: 5).",
            "Set FUZZ_EXCLUDE_PATHS=/docs,/openapi.json in .env to skip read-only routes.",
            "Run: python scripts/run_fuzz.py --base-url http://localhost:8000",
            "Pipe results to a file: python scripts/run_fuzz.py --output fuzz_report.json",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("FUZZ_ITERATIONS", "FUZZ_ITERATIONS: int = 10"),
            ("FUZZ_TIMEOUT_S", "FUZZ_TIMEOUT_S: int = 5"),
            ("FUZZ_EXCLUDE_PATHS", 'FUZZ_EXCLUDE_PATHS: str = "/docs,/openapi.json,/redoc"'),
        ],
    )


