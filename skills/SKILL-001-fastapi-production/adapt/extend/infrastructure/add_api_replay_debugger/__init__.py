"""TOOL-101: add_api_replay_debugger — time-travel debugging for FastAPI.

Generates a ``RequestRecorder`` (Redis ring buffer), ``RequestReplayer``
(re-execute + diff), ``RecorderMiddleware`` (background, zero latency), and
``/debug/requests|replay|flush`` admin endpoints.

The tool is idempotent: a second run detects ``app/debug/recorder.py``
containing ``RequestRecorder`` and returns ``status="no_op"`` without
touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_api_replay_debugger import (
        add_api_replay_debugger,
    )

    result = add_api_replay_debugger(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/debug/recorder.py, ...]
    print(result.next_steps)    # ["Set DEBUG_RECORDER_ENABLED=true", ...]
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base.render import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_api_replay_debugger",
    "description": (
        "Add time-travel API replay debugger: Redis ring buffer captures full "
        "req/resp, replayer re-executes + diffs, admin endpoints for listing and "
        "replaying recorded requests."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_api_replay_debugger",
}

_NOTES_SUCCESS = [
    "API replay debugger added: RequestRecorder ring buffer + RequestReplayer.",
    "RecorderMiddleware captures full req/resp in background (zero latency impact).",
    "Admin routes: GET /debug/requests, POST /debug/replay/{id}, DELETE /debug/flush.",
    "Idempotency key per record: SHA-256 of method+path+sorted(body)+timestamp.",
]
_NEXT_STEPS = [
    "pip install 'redis[hiredis]'",
    "Set DEBUG_RECORDER_ENABLED=true in .env (default: false).",
    "Set REDIS_URL in .env (e.g. redis://localhost:6379/0).",
    "Optional: set DEBUG_RECORDER_TTL_S and DEBUG_RECORDER_MAX_ENTRIES.",
    "Optional: set DEBUG_RECORDER_EXCLUDE_PATHS=comma,separated,paths.",
]
_PREREQ_NOTES = [
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_api_replay_debugger(inp: ToolInput) -> ToolResult:
    """Add API replay debugger to a FastAPI project.

    Writes ``app/debug/`` package (recorder, replayer, models), a
    ``RecorderMiddleware``, and ``/debug/requests|replay|flush`` admin routes.
    Patches ``app/core/config.py`` with debug config fields and registers the
    middleware + router in ``app/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            notes=_PREREQ_NOTES,
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"

    fingerprint_file = app_dir / "debug" / "recorder.py"
    if fingerprint_file.exists() and "RequestRecorder" in fingerprint_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["RequestRecorder already present — replay debugger already enabled, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/debug/ package with recorder, replayer, models.",
                "[dry_run] Would add RecorderMiddleware to app/main.py.",
                "[dry_run] Would add /debug/requests|replay|flush routes.",
                "[dry_run] Would patch app/core/config.py with DEBUG_RECORDER_* fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    debug_dir = app_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "debug_init.py.tmpl", dest=debug_dir / "__init__.py", substitutions={})
    files_created.append(str(debug_dir / "__init__.py"))

    render_to(_HERE, "debug_recorder.py.tmpl", dest=fingerprint_file, substitutions={})
    files_created.append(str(fingerprint_file))

    render_to(_HERE, "debug_replayer.py.tmpl", dest=debug_dir / "replayer.py", substitutions={})
    files_created.append(str(debug_dir / "replayer.py"))

    render_to(_HERE, "debug_models.py.tmpl", dest=debug_dir / "models.py", substitutions={})
    files_created.append(str(debug_dir / "models.py"))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    render_to(
        _HERE,
        "recorder_middleware.py.tmpl",
        dest=middleware_dir / "request_recorder.py",
        substitutions={},
    )
    files_created.append(str(middleware_dir / "request_recorder.py"))

    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        render_to(_HERE, "debug_routes.py.tmpl", dest=routes_dir / "debug.py", substitutions={})
        files_created.append(str(routes_dir / "debug.py"))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=_NOTES_SUCCESS,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_api_replay_debugger_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_api_replay_debugger_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_api_replay_debugger_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject DEBUG_RECORDER_* fields into app/core/config.py Settings.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("DEBUG_RECORDER_ENABLED", "DEBUG_RECORDER_ENABLED: bool = False"),
            ("DEBUG_RECORDER_TTL_S", "DEBUG_RECORDER_TTL_S: int = 3600"),
            ("DEBUG_RECORDER_MAX_ENTRIES", "DEBUG_RECORDER_MAX_ENTRIES: int = 10000"),
            (
                "DEBUG_RECORDER_EXCLUDE_PATHS",
                'DEBUG_RECORDER_EXCLUDE_PATHS: str = "/healthz,/metrics,/debug"',
            ),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Inject recorder init/close + middleware registration into main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "init_recorder" in src:
        return

    recorder_import = (
        "\nfrom app.debug.recorder import init_recorder, close_recorder  "
        "# noqa: F401 — debug recorder\n"
        "import os as _dbg_os\n"
    )
    recorder_startup = (
        "\n# Debug recorder startup — added by add_api_replay_debugger tool\n"
        '_debug_enabled = _dbg_os.getenv("DEBUG_RECORDER_ENABLED", "false").lower() == "true"\n'
        '_debug_redis = _dbg_os.getenv("REDIS_URL", "redis://localhost:6379/0")\n'
        '_debug_ttl = int(_dbg_os.getenv("DEBUG_RECORDER_TTL_S", "3600"))\n'
        '_debug_max = int(_dbg_os.getenv("DEBUG_RECORDER_MAX_ENTRIES", "10000"))\n'
        '_debug_excl = _dbg_os.getenv("DEBUG_RECORDER_EXCLUDE_PATHS", "/healthz,/metrics,/debug")\n'
    )

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + recorder_import,
        )
    else:
        src = recorder_import + src

    src = src.rstrip("\n") + "\n" + recorder_startup
    main_file.write_text(src)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
